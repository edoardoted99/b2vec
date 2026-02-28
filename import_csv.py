#!/usr/bin/env python
"""
Bulk-import companies from the BigPicture CSV into PostgreSQL.

Usage:
    python import_csv.py [--csv companies-2023-q4-sm.csv] [--country IT] [--batch 50000]

Uses COPY-style bulk insert for speed (~17M rows).
Skips rows without a website and deduplicates on handle.
"""

import os
import sys
import csv
import argparse
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.db import connection
from core.models import Company


def import_csv(csv_path: str, country_code: str | None, batch_size: int):
    print(f"Reading {csv_path} ...")
    if country_code:
        print(f"Filtering by country_code = {country_code}")

    # Get existing handles to skip duplicates
    print("Loading existing handles from DB ...")
    existing_handles = set(
        Company.objects.values_list('handle', flat=True)
    )
    print(f"  {len(existing_handles)} companies already in DB")

    batch = []
    total_inserted = 0
    total_skipped = 0
    t0 = time.time()

    with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Filter by country
            if country_code and row.get('country_code', '').strip() != country_code:
                continue

            # Must have website
            website = (row.get('website') or '').strip()
            if not website:
                total_skipped += 1
                continue

            handle = (row.get('handle') or '').strip() or None

            # Skip duplicates
            if handle and handle in existing_handles:
                total_skipped += 1
                continue

            name = (row.get('name') or '').strip()
            if not name:
                total_skipped += 1
                continue

            batch.append(Company(
                handle=handle,
                name=name[:255],
                website=website[:255],
                url=f"https://www.{website}",
                industry=(row.get('industry') or '').strip()[:255] or None,
                size=(row.get('size') or '').strip()[:50] or None,
                type=(row.get('type') or '').strip()[:100] or None,
                founded=(row.get('founded') or '').strip()[:10] or None,
                city=(row.get('city') or '').strip()[:255] or None,
                state=(row.get('state') or '').strip()[:255] or None,
                country_code=(row.get('country_code') or '').strip()[:10] or None,
                scrape_status='pending',
            ))

            if handle:
                existing_handles.add(handle)

            if len(batch) >= batch_size:
                Company.objects.bulk_create(batch, ignore_conflicts=True)
                total_inserted += len(batch)
                elapsed = time.time() - t0
                rate = total_inserted / elapsed if elapsed > 0 else 0
                print(f"  Inserted {total_inserted:,} ({rate:,.0f}/s) | Skipped {total_skipped:,}")
                batch = []

    # Final batch
    if batch:
        Company.objects.bulk_create(batch, ignore_conflicts=True)
        total_inserted += len(batch)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Inserted: {total_inserted:,}")
    print(f"  Skipped:  {total_skipped:,}")
    print(f"  Total in DB: {Company.objects.count():,}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Import companies from CSV")
    parser.add_argument('--csv', default='companies-2023-q4-sm.csv', help='Path to CSV file')
    parser.add_argument('--country', default=None, help='Filter by country code (e.g. IT). Default: all countries')
    parser.add_argument('--batch', type=int, default=50000, help='Bulk insert batch size')
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"ERROR: CSV file not found: {args.csv}")
        sys.exit(1)

    import_csv(args.csv, args.country, args.batch)
