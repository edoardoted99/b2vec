import logging

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

logger = logging.getLogger(__name__)


def extract_text(html):
    """Extract clean text from HTML, stripping boilerplate."""
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    return '\n'.join(chunk for chunk in chunks if chunk)


def scrape_company(company):
    """
    Scrape a company's website. Tries URL variants.
    Returns (success: bool, message: str).
    """
    from core.models import ScrapedData

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
    }

    domain = company.website or ''
    if not domain and company.url:
        domain = company.url.replace('https://', '').replace('http://', '').rstrip('/')

    if not domain:
        company.scrape_status = 'error'
        company.scrape_error_type = 'no_url'
        company.scrape_error_detail = 'No website or URL available'
        company.save(update_fields=['scrape_status', 'scrape_error_type', 'scrape_error_detail'])
        return False, 'No URL'

    # Clean domain
    domain = domain.replace('https://', '').replace('http://', '').replace('www.', '').rstrip('/')

    url_variants = [
        f'https://www.{domain}',
        f'https://{domain}',
        f'http://www.{domain}',
    ]

    company.scrape_status = 'in_progress'
    company.save(update_fields=['scrape_status'])

    last_error = None
    for url in url_variants:
        try:
            response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            response.raise_for_status()
            text = extract_text(response.content)

            if len(text) < 50:
                last_error = 'Content too short'
                continue

            ScrapedData.objects.update_or_create(
                company=company,
                defaults={
                    'text_content': text,
                    'cleaned_content': text[:10000],
                }
            )

            company.scrape_status = 'success'
            company.scraped_at = timezone.now()
            company.scrape_error_type = None
            company.scrape_error_detail = None
            company.save(update_fields=['scrape_status', 'scraped_at', 'scrape_error_type', 'scrape_error_detail'])
            return True, 'OK'

        except requests.exceptions.Timeout:
            last_error = 'timeout'
        except requests.exceptions.ConnectionError:
            last_error = 'connection'
        except requests.exceptions.HTTPError as e:
            last_error = f'http_{e.response.status_code}'
        except Exception as e:
            last_error = str(e)[:200]

    company.scrape_status = 'error'
    company.scrape_error_type = last_error[:50] if last_error else 'unknown'
    company.scrape_error_detail = last_error
    company.save(update_fields=['scrape_status', 'scrape_error_type', 'scrape_error_detail'])
    return False, last_error or 'Unknown error'
