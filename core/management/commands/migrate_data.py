import sqlite3

from django.core.management.base import BaseCommand
from django.db import connection

from core.models import Company, ScrapedData


class Command(BaseCommand):
    help = 'Migrate data from db.sqlite3 to PostgreSQL'

    def add_arguments(self, parser):
        parser.add_argument(
            '--sqlite-path',
            default='db.sqlite3',
            help='Path to the SQLite database file',
        )

    def handle(self, *args, **options):
        sqlite_path = options['sqlite_path']
        self.stdout.write(f'Reading from {sqlite_path}...')

        conn = sqlite3.connect(sqlite_path)
        conn.row_factory = sqlite3.Row

        # Migrate companies
        cursor = conn.execute('SELECT * FROM core_company ORDER BY id')
        rows = cursor.fetchall()
        self.stdout.write(f'Found {len(rows)} companies in SQLite')

        companies = []
        for row in rows:
            companies.append(Company(
                id=row['id'],
                handle=row['handle'] if 'handle' in row.keys() else None,
                name=row['name'],
                url=row['url'] if 'url' in row.keys() else None,
                website=row['website'] if 'website' in row.keys() else None,
                industry=row['industry'] if 'industry' in row.keys() else None,
                size=row['size'] if 'size' in row.keys() else None,
                type=row['type'] if 'type' in row.keys() else None,
                founded=row['founded'] if 'founded' in row.keys() else None,
                city=row['city'] if 'city' in row.keys() else None,
                state=row['state'] if 'state' in row.keys() else None,
                country_code=row['country_code'] if 'country_code' in row.keys() else None,
                scrape_status=row['scrape_status'] if 'scrape_status' in row.keys() else 'pending',
                scrape_error_type=row['scrape_error_type'] if 'scrape_error_type' in row.keys() else None,
                scrape_error_detail=row['scrape_error_detail'] if 'scrape_error_detail' in row.keys() else None,
                scraped_at=row['scraped_at'] if 'scraped_at' in row.keys() else None,
            ))

        if companies:
            Company.objects.bulk_create(companies, ignore_conflicts=True)
            self.stdout.write(self.style.SUCCESS(f'Migrated {len(companies)} companies'))

        # Migrate scraped data
        cursor = conn.execute('SELECT * FROM core_scrapeddata ORDER BY id')
        rows = cursor.fetchall()
        self.stdout.write(f'Found {len(rows)} scraped data records in SQLite')

        scraped = []
        for row in rows:
            scraped.append(ScrapedData(
                id=row['id'],
                company_id=row['company_id'],
                text_content=row['text_content'],
                cleaned_content=row['cleaned_content'] if 'cleaned_content' in row.keys() else None,
            ))

        if scraped:
            ScrapedData.objects.bulk_create(scraped, ignore_conflicts=True)
            self.stdout.write(self.style.SUCCESS(f'Migrated {len(scraped)} scraped records'))

        conn.close()

        # Reset sequences
        with connection.cursor() as cur:
            cur.execute(
                "SELECT setval(pg_get_serial_sequence('core_company', 'id'), "
                "COALESCE((SELECT MAX(id) FROM core_company), 1));"
            )
            cur.execute(
                "SELECT setval(pg_get_serial_sequence('core_scrapeddata', 'id'), "
                "COALESCE((SELECT MAX(id) FROM core_scrapeddata), 1));"
            )

        self.stdout.write(self.style.SUCCESS('Data migration complete. Sequences reset.'))
