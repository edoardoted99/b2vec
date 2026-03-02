#!/usr/bin/env python
"""
Compute UMAP projections and HDBSCAN clusters from embeddings.

Usage:
    python compute_projections.py [--neighbors 15] [--min-dist 0.1] [--min-cluster 5]
"""

import os
import argparse
import logging
from collections import Counter

import numpy as np

# ---------------------------------------------------------------------------
# Django setup
# ---------------------------------------------------------------------------

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from core.models import CompanyEmbedding

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Compute UMAP + HDBSCAN from embeddings")
    parser.add_argument('--neighbors', type=int, default=15, help='UMAP n_neighbors')
    parser.add_argument('--min-dist', type=float, default=0.1, help='UMAP min_dist')
    parser.add_argument('--min-cluster', type=int, default=5, help='HDBSCAN min_cluster_size')
    parser.add_argument('--min-samples', type=int, default=3, help='HDBSCAN min_samples')
    parser.add_argument('--max-clusters', type=int, default=None, help='Keep only the N largest clusters (rest becomes Noise)')
    args = parser.parse_args()

    embeddings = list(
        CompanyEmbedding.objects.select_related('company').all()
    )

    if len(embeddings) < 3:
        logger.info(f"Only {len(embeddings)} embeddings — need at least 3.")
        return

    logger.info(f"Computing projections for {len(embeddings)} embeddings...")

    vectors = np.array([emb.vector for emb in embeddings])

    # --- UMAP ---
    import umap
    logger.info(f"UMAP: n_neighbors={args.neighbors}, min_dist={args.min_dist}")
    n_neighbors = min(args.neighbors, len(vectors) - 1)
    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=max(2, n_neighbors),
        min_dist=args.min_dist,
        metric='cosine',
        random_state=42,
    )
    coords = reducer.fit_transform(vectors)
    logger.info("UMAP done.")

    # --- HDBSCAN ---
    import hdbscan
    logger.info(f"HDBSCAN: min_cluster_size={args.min_cluster}, min_samples={args.min_samples}")
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=args.min_cluster,
        min_samples=args.min_samples,
        metric='euclidean',
    )
    clusterer.fit(coords)
    labels = clusterer.labels_
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int((labels == -1).sum())
    logger.info(f"HDBSCAN done: {n_clusters} clusters, {n_noise} noise points.")

    # --- Cap clusters if --max-clusters is set ---
    if args.max_clusters and n_clusters > args.max_clusters:
        cluster_counts = Counter(l for l in labels if l != -1)
        keep = set(cid for cid, _ in cluster_counts.most_common(args.max_clusters))
        labels = np.array([l if l in keep else -1 for l in labels])
        # Re-number clusters 0..N-1
        remap = {old: new for new, old in enumerate(sorted(keep))}
        labels = np.array([remap[l] if l in remap else -1 for l in labels])
        n_clusters = len(remap)
        n_noise = int((labels == -1).sum())
        logger.info(f"Capped to {n_clusters} clusters, {n_noise} noise points.")

    # --- Cluster labels from most common industry ---
    cluster_industries = {}
    for i, emb in enumerate(embeddings):
        cid = int(labels[i])
        if cid == -1:
            continue
        industry = emb.company.industry or 'Unknown'
        cluster_industries.setdefault(cid, []).append(industry)

    cluster_labels = {}
    for cid, industries in cluster_industries.items():
        most_common = Counter(industries).most_common(1)[0][0]
        cluster_labels[cid] = most_common

    # --- Update DB ---
    logger.info("Writing to DB...")
    for i, emb in enumerate(embeddings):
        emb.umap_x = float(coords[i][0])
        emb.umap_y = float(coords[i][1])
        emb.cluster_id = int(labels[i])
        emb.cluster_label = cluster_labels.get(int(labels[i]), 'Noise')

    CompanyEmbedding.objects.bulk_update(
        embeddings, ['umap_x', 'umap_y', 'cluster_id', 'cluster_label']
    )

    logger.info(f"Done. Updated {len(embeddings)} embeddings.")


if __name__ == '__main__':
    main()
