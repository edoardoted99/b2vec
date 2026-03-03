#!/usr/bin/env python
"""
Extract structured company properties from scraped text using Ollama.

Usage:
    python extract_properties.py [--batch 50] [--model qwen3:8b]
"""

import os
import json
import argparse
import logging

import requests
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Django setup
# ---------------------------------------------------------------------------

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.conf import settings
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

# Limit text sent to the model (~2k tokens ≈ 6000 chars)
MAX_TEXT_CHARS = 6000


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
    parser.add_argument('--batch', type=int, default=50, help='Progress save interval')
    parser.add_argument('--model', default='qwen3:8b', help='Ollama model name')
    args = parser.parse_args()

    # Skip companies already extracted with the SAME model
    already_done = set(
        CompanyProperties.objects
        .filter(extracted_at__isnull=False, model_name=args.model)
        .values_list('company_id', flat=True)
    )
    scraped = list(
        ScrapedData.objects
        .filter(text_content__isnull=False)
        .exclude(company_id__in=already_done)
        .order_by('company_id')
        .distinct('company_id')
        .select_related('company')
    )
    scraped = [s for s in scraped if len(s.text_content.strip()) > 0]

    logger.info(f"Companies to process: {len(scraped)} (model: {args.model})")
    if not scraped:
        logger.info("Nothing to process.")
        return

    extracted = 0
    errors = 0

    for item in tqdm(scraped, desc="Extracting", unit="company"):
        try:
            data = extract_properties(item.text_content, item.company.name, args.model)
            save_properties(item.company_id, data, args.model)
            extracted += 1
        except Exception as exc:
            errors += 1
            logger.warning(f"Failed {item.company.name}: {exc}")
            continue

    logger.info(f"Done. Extracted: {extracted}, Errors: {errors}")


if __name__ == '__main__':
    main()
