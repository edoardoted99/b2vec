#!/usr/bin/env python
"""
Async bulk scraper for Italian companies.

Usage:
    python web_scraper.py [--csv PATH] [--country IT] [--concurrency 50]

Resumes automatically — only scrapes companies with scrape_status != 'success'.
"""

import os
import sys
import asyncio
import argparse
import logging
from datetime import timezone as tz

import aiohttp
import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Django setup
# ---------------------------------------------------------------------------

def setup_django():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()


setup_django()

from django.utils import timezone
from core.models import Company, ScrapedData

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSV Import
# ---------------------------------------------------------------------------

def import_companies_from_csv(csv_path: str, country_code: str = 'IT') -> int:
    """Import companies from CSV, filtering by country_code. Returns count of new rows."""
    logger.info(f"Reading CSV: {csv_path}")
    df = pd.read_csv(csv_path)

    # Filter by country
    if country_code:
        df = df[df['country_code'] == country_code]
    logger.info(f"Filtered to {len(df)} rows (country_code={country_code})")

    # Drop rows without website
    df = df[df['website'].notna() & (df['website'].str.strip() != '')]
    logger.info(f"{len(df)} rows with a website")

    # Get existing handles to skip duplicates (batch to avoid SQLite variable limit)
    all_handles = df['handle'].tolist()
    existing_handles = set()
    batch_size = 900
    for i in range(0, len(all_handles), batch_size):
        batch = all_handles[i:i + batch_size]
        existing_handles.update(
            Company.objects.filter(handle__in=batch)
            .values_list('handle', flat=True)
        )

    new_companies = []
    for _, row in df.iterrows():
        handle = row.get('handle')
        if handle in existing_handles:
            continue
        new_companies.append(Company(
            handle=handle,
            name=row.get('name', ''),
            website=row.get('website', ''),
            url=f"https://www.{row['website'].strip()}",
            industry=row.get('industry') if pd.notna(row.get('industry')) else None,
            size=row.get('size') if pd.notna(row.get('size')) else None,
            type=row.get('type') if pd.notna(row.get('type')) else None,
            founded=str(int(row['founded'])) if pd.notna(row.get('founded')) else None,
            city=row.get('city') if pd.notna(row.get('city')) else None,
            state=row.get('state') if pd.notna(row.get('state')) else None,
            country_code=row.get('country_code') if pd.notna(row.get('country_code')) else None,
            scrape_status='pending',
        ))

    if new_companies:
        Company.objects.bulk_create(new_companies, batch_size=1000, ignore_conflicts=True)
        logger.info(f"Inserted {len(new_companies)} new companies")
    else:
        logger.info("No new companies to insert")

    return len(new_companies)


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text(html: str) -> str:
    """Extract readable text from HTML, stripping boilerplate tags."""
    soup = BeautifulSoup(html, 'html.parser')

    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]):
        tag.decompose()

    text = soup.get_text(separator='\n')
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    return '\n'.join(chunk for chunk in chunks if chunk)


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

def classify_error(exc: Exception, status: int | None = None) -> str:
    """Return a short error-type tag from an exception or HTTP status."""
    if status is not None:
        if 400 <= status < 500:
            return 'http_4xx'
        if 500 <= status < 600:
            return 'http_5xx'

    name = type(exc).__name__.lower()
    msg = str(exc).lower()

    if 'dns' in msg or 'nodename' in msg or 'name or service not known' in msg or 'getaddrinfo' in msg:
        return 'dns_error'
    if 'timeout' in name or 'timeout' in msg:
        return 'timeout'
    if 'ssl' in name or 'ssl' in msg or 'certificate' in msg:
        return 'ssl_error'
    if 'connect' in name or 'connect' in msg:
        return 'connection_error'
    return 'other_error'


# ---------------------------------------------------------------------------
# Single-URL scraper
# ---------------------------------------------------------------------------

async def scrape_one(
    session: aiohttp.ClientSession,
    company: Company,
    timeout: aiohttp.ClientTimeout,
) -> tuple[bool, str | None, str | None, str | None]:
    """
    Scrape a single company URL.
    Returns (success, text, error_type, error_detail).
    """
    domain = company.website.strip()
    urls_to_try = [f"https://www.{domain}", f"https://{domain}", f"http://www.{domain}", f"http://{domain}"]

    last_error: Exception | None = None

    for url in urls_to_try:
        try:
            async with session.get(url, timeout=timeout, allow_redirects=True, ssl=False) as resp:
                if resp.status >= 400:
                    last_error = Exception(f"HTTP {resp.status}")
                    continue
                html = await resp.text(errors='replace')
                text = extract_text(html)
                if not text.strip():
                    return False, None, 'parse_error', 'Extracted text is empty'
                return True, text, None, None
        except Exception as exc:
            last_error = exc
            continue

    # All attempts failed
    error_type = classify_error(last_error, None)
    return False, None, error_type, str(last_error)[:500]


# ---------------------------------------------------------------------------
# Batch scraper
# ---------------------------------------------------------------------------

async def scrape_batch(companies: list[Company], concurrency: int = 50):
    """Scrape a list of companies with bounded concurrency."""
    sem = asyncio.Semaphore(concurrency)
    timeout = aiohttp.ClientTimeout(total=15)
    connector = aiohttp.TCPConnector(limit=concurrency, ttl_dns_cache=300)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
    }

    pbar = tqdm(total=len(companies), desc="Scraping", unit="site")
    success_count = 0
    error_count = 0

    # Batch DB writes to avoid per-row overhead
    WRITE_BATCH = 50
    scraped_buf: list[tuple[Company, str]] = []
    error_buf: list[tuple[Company, str, str]] = []

    def flush_buffers():
        nonlocal scraped_buf, error_buf
        now = timezone.now()

        # Save successful scrapes
        for company, text in scraped_buf:
            ScrapedData.objects.update_or_create(
                company=company,
                defaults={'text_content': text},
            )
            Company.objects.filter(pk=company.pk).update(
                scrape_status='success',
                scrape_error_type=None,
                scrape_error_detail=None,
                scraped_at=now,
            )

        # Save errors
        for company, etype, edetail in error_buf:
            Company.objects.filter(pk=company.pk).update(
                scrape_status='error',
                scrape_error_type=etype,
                scrape_error_detail=edetail,
                scraped_at=now,
            )

        scraped_buf = []
        error_buf = []

    async def _worker(company: Company):
        nonlocal success_count, error_count
        async with sem:
            ok, text, etype, edetail = await scrape_one(session, company, timeout)

        if ok:
            scraped_buf.append((company, text))
            success_count += 1
        else:
            error_buf.append((company, etype, edetail))
            error_count += 1

        if len(scraped_buf) + len(error_buf) >= WRITE_BATCH:
            await asyncio.to_thread(flush_buffers)

        pbar.update(1)
        pbar.set_postfix(ok=success_count, err=error_count)

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        tasks = [asyncio.create_task(_worker(c)) for c in companies]
        await asyncio.gather(*tasks, return_exceptions=True)

    # Flush remaining
    flush_buffers()
    pbar.close()
    logger.info(f"Done. Success: {success_count}, Errors: {error_count}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Bulk async scraper for companies")
    parser.add_argument('--csv', default='companies-2023-q4-sm.csv', help='Path to CSV file')
    parser.add_argument('--country', default='IT', help='Country code to filter')
    parser.add_argument('--concurrency', type=int, default=50, help='Max concurrent requests')
    parser.add_argument('--skip-csv', action='store_true', help='Skip CSV import (use existing DB data)')
    args = parser.parse_args()

    # Phase 1: CSV import
    if not args.skip_csv:
        import_companies_from_csv(args.csv, args.country)
    else:
        logger.info("Skipping CSV import (--skip-csv)")

    # Phase 2: Scrape pending/errored companies
    companies = list(Company.objects.exclude(scrape_status='success').filter(website__isnull=False))
    logger.info(f"Companies to scrape: {len(companies)}")

    if not companies:
        logger.info("Nothing to scrape — all companies already scraped successfully.")
        return

    asyncio.run(scrape_batch(companies, concurrency=args.concurrency))


if __name__ == '__main__':
    main()
