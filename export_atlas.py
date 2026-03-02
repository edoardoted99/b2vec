#!/usr/bin/env python
"""
Export embedding data as Parquet for use with embedding-atlas CLI.

Usage:
    python export_atlas.py [--output atlas_data.parquet]

Then open with:
    embedding-atlas atlas_data.parquet --text description
"""

import os
import argparse

# ---------------------------------------------------------------------------
# Django setup
# ---------------------------------------------------------------------------

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

import pandas as pd
from core.models import CompanyEmbedding


def main():
    parser = argparse.ArgumentParser(description="Export embedding data as Parquet for Atlas")
    parser.add_argument('--output', '-o', type=str, default='atlas_data.parquet',
                        help='Output Parquet file path (default: atlas_data.parquet)')
    args = parser.parse_args()

    print("Querying embeddings with company data...")

    rows = list(
        CompanyEmbedding.objects
        .select_related('company')
        .filter(umap_x__isnull=False)
        .values_list(
            'company__name',
            'company__url',
            'company__industry',
            'company__city',
            'company__country_code',
            'company__size',
            'company__founded',
            'umap_x',
            'umap_y',
            'cluster_id',
            'cluster_label',
            'company__properties__description',
        )
    )

    print(f"Found {len(rows)} embeddings with projections.")

    if not rows:
        print("No data to export.")
        return

    df = pd.DataFrame(rows, columns=[
        'name', 'url', 'industry', 'city', 'country_code',
        'size', 'founded',
        'projection_x', 'projection_y',
        'cluster_label_id', 'cluster_label',
        'description',
    ])

    # Fill NaN for string columns
    for col in ['name', 'url', 'industry', 'city', 'country_code',
                'size', 'founded', 'cluster_label', 'description']:
        df[col] = df[col].fillna('')

    df.to_parquet(args.output, index=False)
    print(f"Saved {len(df)} rows to {args.output}")


if __name__ == '__main__':
    main()
