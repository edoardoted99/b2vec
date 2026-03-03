#!/usr/bin/env python
"""
Extract structured company properties from scraped text using Ollama.

Re-processes companies that are missing phone or email.
If extraction from scraped text fails to find phone/email, falls back
to fetching the company website directly.

Usage:
    python extract_properties.py [--model qwen3:8b]
"""

import os
import json
import argparse
import logging

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Django setup
# ---------------------------------------------------------------------------

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.conf import settings
from django.db.models import Q
from core.models import ScrapedData, CompanyProperties

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

OLLAMA_URL = f"{settings.OLLAMA_BASE_URL}/api/chat"

# JSON schema for structured output
PROPERTIES_SCHEMA = {
    "type": "object",
    "properties": {
        "phone": {
            "type": ["string", "null"],
            "description": "Main phone number",
        },
        "email": {
            "type": ["string", "null"],
            "description": "Main contact email",
        },
        "vat_number": {
            "type": ["string", "null"],
            "description": "VAT number / Partita IVA",
        },
        "address": {
            "type": ["string", "null"],
            "description": "Full address (street, city, zip)",
        },
        "description": {
            "type": ["string", "null"],
            "description": "Brief description of what the company does (2-3 sentences max)",
        },
        "services": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of main services or products offered",
        },
        "linkedin": {
            "type": ["string", "null"],
            "description": "LinkedIn profile URL",
        },
        "facebook": {
            "type": ["string", "null"],
            "description": "Facebook page URL",
        },
        "instagram": {
            "type": ["string", "null"],
            "description": "Instagram profile URL",
        },
    },
    "required": [
        "phone", "email", "vat_number", "address",
        "description", "services", "linkedin", "facebook", "instagram",
    ],
}

SYSTEM_PROMPT = (
    "You are a data extraction assistant. "
    "Extract company information from the provided website text. "
    "Only extract information that is explicitly present in the text. "
    "If a field is not found, return null. "
    "For services, list only the main ones (max 10). "
    "Return JSON only."
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
}

# Limit text sent to the model (~2k tokens ≈ 6000 chars)
MAX_TEXT_CHARS = 6000


def fetch_website_text(domain: str) -> str | None:
    """Fetch and extract text from a company website."""
    domain = domain.replace('https://', '').replace('http://', '').replace('www.', '').rstrip('/')
    urls = [
        f'https://www.{domain}',
        f'https://{domain}',
        f'http://www.{domain}',
    ]
    # Try contact/contatti pages first, then homepage
    paths = ['/contatti', '/contacts', '/contact', '/contattaci', '']
    for base_url in urls:
        for path in paths:
            url = base_url + path
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.content, 'html.parser')
                for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                    tag.decompose()
                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                clean = '\n'.join(chunk for chunk in chunks if chunk)
                if len(clean) > 50:
                    return clean
            except Exception:
                continue
    return None


def extract_properties(text: str, company_name: str, model: str) -> dict:
    """Call Ollama chat API with structured output."""
    truncated = text[:MAX_TEXT_CHARS]

    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Extract properties for the company '{company_name}' from the following website text:\n\n{truncated}",
                },
            ],
            "format": PROPERTIES_SCHEMA,
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    return json.loads(content)


def merge_properties(existing: dict, new_data: dict) -> dict:
    """Merge new extraction into existing, filling only missing fields."""
    merged = dict(existing)
    for key, value in new_data.items():
        if not merged.get(key) and value:
            merged[key] = value
    return merged


def save_properties(company_id: int, data: dict, model: str):
    """Save extracted properties to DB."""
    from django.utils import timezone

    CompanyProperties.objects.update_or_create(
        company_id=company_id,
        defaults={
            "phone": data.get("phone") or None,
            "email": data.get("email") or None,
            "vat_number": data.get("vat_number") or None,
            "address": data.get("address") or None,
            "description": data.get("description") or None,
            "services": data.get("services") or [],
            "linkedin": data.get("linkedin") or None,
            "facebook": data.get("facebook") or None,
            "instagram": data.get("instagram") or None,
            "model_name": model,
            "extracted_at": timezone.now(),
        },
    )


def main():
    parser = argparse.ArgumentParser(description="Extract company properties via Ollama")
    parser.add_argument('--model', default='qwen3:8b', help='Ollama model name')
    args = parser.parse_args()

    # Companies missing phone or email (never extracted, or extracted but incomplete)
    missing_props = set(
        CompanyProperties.objects
        .filter(Q(phone__isnull=True) | Q(email__isnull=True))
        .values_list('company_id', flat=True)
    )
    never_extracted = set(
        ScrapedData.objects
        .filter(text_content__isnull=False)
        .exclude(company_id__in=CompanyProperties.objects.values_list('company_id', flat=True))
        .values_list('company_id', flat=True)
    )
    to_process_ids = missing_props | never_extracted

    scraped = list(
        ScrapedData.objects
        .filter(text_content__isnull=False, company_id__in=to_process_ids)
        .order_by('company_id')
        .distinct('company_id')
        .select_related('company')
    )
    scraped = [s for s in scraped if len(s.text_content.strip()) > 0]

    logger.info(f"Companies to process: {len(scraped)} (model: {args.model})")
    logger.info(f"  - never extracted: {len(never_extracted)}")
    logger.info(f"  - missing phone/email: {len(missing_props)}")
    if not scraped:
        logger.info("Nothing to process.")
        return

    extracted = 0
    errors = 0
    web_fallbacks = 0

    for item in tqdm(scraped, desc="Extracting", unit="company"):
        company = item.company
        try:
            # First pass: extract from scraped text
            data = extract_properties(item.text_content, company.name, args.model)
            logger.info(f"[{company.name}] Extracted from scraped text — phone: {data.get('phone')}, email: {data.get('email')}")

            # If phone or email still missing, try fetching website directly
            if not data.get('phone') or not data.get('email'):
                domain = company.website or company.url
                if domain:
                    logger.info(f"[{company.name}] Missing phone/email, fetching website: {domain}")
                    web_text = fetch_website_text(domain)
                    if web_text:
                        web_data = extract_properties(web_text, company.name, args.model)
                        logger.info(f"[{company.name}] Web fallback result — phone: {web_data.get('phone')}, email: {web_data.get('email')}")
                        data = merge_properties(data, web_data)
                        web_fallbacks += 1
                    else:
                        logger.info(f"[{company.name}] Web fallback failed, no content retrieved")
                else:
                    logger.info(f"[{company.name}] No website URL available for fallback")

            save_properties(company.id, data, args.model)
            extracted += 1
            logger.info(f"[{company.name}] Saved — phone: {data.get('phone')}, email: {data.get('email')}")

        except Exception as exc:
            errors += 1
            logger.warning(f"[{company.name}] FAILED: {exc}")
            continue

    logger.info(f"Done. Extracted: {extracted}, Errors: {errors}, Web fallbacks: {web_fallbacks}")


if __name__ == '__main__':
    main()
