import requests
from bs4 import BeautifulSoup
from django.utils import timezone
from core.models import Company, ScrapedData
import logging

logger = logging.getLogger(__name__)

def scrape_website(company: Company):
    """
    Fetches the company's URL, extracts text, and saves to ScrapedData.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7'
    }

    try:
        response = requests.get(company.url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()
            
        # Get text
        text = soup.get_text()
        
        # Break into lines and remove leading/trailing space on each
        lines = (line.strip() for line in text.splitlines())
        # Break multi-headlines into a line each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        # Drop blank lines
        cleaned_text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Save to DB
        # Check if scraped data already exists, update it or create new
        scraped_data, created = ScrapedData.objects.update_or_create(
            company=company,
            defaults={
                'text_content': cleaned_text,
                'scraped_at': timezone.now()
            }
        )
        return True, "Success"

    except Exception as e:
        logger.error(f"Error scraping {company.url}: {e}")
        return False, str(e)
