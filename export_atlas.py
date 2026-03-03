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

import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors

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
            'company__properties__phone',
            'company__properties__email',
            'company__properties__vat_number',
            'company__properties__address',
            'company__properties__services',
            'company__properties__linkedin',
            'company__properties__facebook',
            'company__properties__instagram',
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
        'phone', 'email', 'vat_number', 'address',
        'services', 'linkedin', 'facebook', 'instagram',
    ])

    # Convert services list to comma-separated string
    df['services'] = df['services'].apply(
        lambda v: ', '.join(v) if isinstance(v, list) else ''
    )

    # Fill NaN for string columns
    str_cols = [
        'name', 'url', 'industry', 'city', 'country_code',
        'size', 'founded', 'cluster_label', 'description',
        'phone', 'email', 'vat_number', 'address',
        'services', 'linkedin', 'facebook', 'instagram',
    ]
    for col in str_cols:
        df[col] = df[col].fillna('')

    # --- Compute nearest neighbors from embedding vectors ---
    print("Loading embedding vectors...")
    embeddings = list(
        CompanyEmbedding.objects
        .filter(umap_x__isnull=False)
        .order_by('pk')
        .values_list('vector', flat=True)
    )
    vectors = np.array([list(v) for v in embeddings], dtype=np.float32)

    k = min(20, len(vectors) - 1)
    print(f"Computing {k} nearest neighbors for {len(vectors)} points...")
    nn = NearestNeighbors(n_neighbors=k + 1, metric='cosine', algorithm='brute')
    nn.fit(vectors)
    distances, indices = nn.kneighbors(vectors)

    # Build neighbors column as dicts (skip self at index 0)
    df['neighbors'] = [
        {'ids': indices[i, 1:].tolist(), 'distances': np.round(distances[i, 1:], 6).tolist()}
        for i in range(len(vectors))
    ]

    df.to_parquet(args.output, index=False)
    print(f"Saved {len(df)} rows to {args.output}")


if __name__ == '__main__':
    main()
