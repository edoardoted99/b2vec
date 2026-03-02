#!/usr/bin/env python
"""
Generate embeddings for scraped companies using Ollama (embeddinggemma).

Usage:
    python generate_embeddings.py [--batch 50] [--model embeddinggemma]
"""

import os
import sys
import argparse
import logging

import numpy as np
import requests
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Django setup
# ---------------------------------------------------------------------------

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.conf import settings
from core.models import Company, ScrapedData, CompanyEmbedding

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

OLLAMA_URL = f"{settings.OLLAMA_BASE_URL}/api/embed"
CHUNK_CHARS = 6000  # ~2k tokens for Gemma tokenizer


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """Split text into chunks of approximately max_chars."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    for i in range(0, len(text), max_chars):
        chunks.append(text[i:i + max_chars])
    return chunks


def get_embedding(text: str, model: str) -> list[float]:
    """Embed text via Ollama. For long texts, chunk and average vectors."""
    chunks = chunk_text(text)
    if len(chunks) == 1:
        resp = requests.post(OLLAMA_URL, json={"model": model, "input": chunks[0]}, timeout=60)
        resp.raise_for_status()
        return resp.json()["embeddings"][0]

    # Embed all chunks in one call
    resp = requests.post(OLLAMA_URL, json={"model": model, "input": chunks}, timeout=120)
    resp.raise_for_status()
    vectors = np.array(resp.json()["embeddings"])
    avg = vectors.mean(axis=0)
    # L2-normalize so cosine distance works correctly
    avg = avg / np.linalg.norm(avg)
    return avg.tolist()


def main():
    parser = argparse.ArgumentParser(description="Generate embeddings via Ollama")
    parser.add_argument('--batch', type=int, default=50, help='DB write batch size')
    parser.add_argument('--model', default=settings.OLLAMA_EMBED_MODEL, help='Ollama model name')
    args = parser.parse_args()

    # Companies with scraped text that don't have an embedding yet
    existing_ids = set(
        CompanyEmbedding.objects.values_list('company_id', flat=True)
    )
    scraped = list(
        ScrapedData.objects
        .filter(text_content__isnull=False)
        .exclude(company_id__in=existing_ids)
        .order_by('company_id')
        .distinct('company_id')
        .select_related('company')
    )
    scraped = [s for s in scraped if len(s.text_content.strip()) > 0]

    logger.info(f"Companies to embed: {len(scraped)} (model: {args.model})")
    if not scraped:
        logger.info("Nothing to embed.")
        return

    buf: list[CompanyEmbedding] = []
    errors = 0

    for item in tqdm(scraped, desc="Embedding", unit="company"):
        try:
            vec = get_embedding(item.text_content, args.model)
            buf.append(CompanyEmbedding(company_id=item.company_id, vector=vec))
        except Exception as exc:
            errors += 1
            logger.warning(f"Failed {item.company.name}: {exc}")
            continue

        if len(buf) >= args.batch:
            CompanyEmbedding.objects.bulk_create(buf, ignore_conflicts=True)
            buf.clear()

    if buf:
        CompanyEmbedding.objects.bulk_create(buf, ignore_conflicts=True)

    total = len(scraped) - errors
    logger.info(f"Done. Embedded: {total}, Errors: {errors}")


if __name__ == '__main__':
    main()
