import json
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD, PCA
from core.models import Company, ScrapedData, CompanyEmbedding
from django.utils import timezone

ITALIAN_STOPWORDS = [
    'di', 'a', 'da', 'in', 'con', 'su', 'per', 'tra', 'fra', 'il', 'lo', 'la', 'i', 'gli', 'le',
    'un', 'uno', 'una', 'e', 'ed', 'o', 'ma', 'se', 'che', 'non', 'si', 'ci', 'vi', 'li', 'ne',
    'chi', 'cui', 'quale', 'dove', 'come', 'quando', 'perché', 'più', 'meno', 'bene', 'male', 'siamo',
    'sei', 'è', 'sono', 'stato', 'stata', 'stati', 'state', 'hanno', 'abbiamo', 'avete', 'srl', 'spa',
    'inc', 'co', 'azienda', 'servizi', 'prodotti', 'contatti', 'chi', 'siamo', 'home', 'page', 'cookie',
    'policy', 'privacy', 'rights', 'reserved', 'copyright', 'iva', 'piva', 'tel', 'fax', 'email', 'info'
]

def generate_embeddings():
    """
    Generates embeddings for all scraped companies using TF-IDF + SVD (LSA).
    """
    scraped_items = ScrapedData.objects.select_related('company').all()
    if not scraped_items.exists():
        return False, "No data to process"

    documents = []
    company_ids = []
    
    for item in scraped_items:
        if item.text_content and len(item.text_content) > 50:
            documents.append(item.text_content)
            company_ids.append(item.company.id)

    if len(documents) < 2:
        return False, "Not enough documents to build a model (need at least 2)"

    # 1. TF-IDF Vectorization
    vectorizer = TfidfVectorizer(
        max_features=2000, 
        stop_words=ITALIAN_STOPWORDS,
        min_df=1,    # Allow words that appear in only 1 doc for now (small corpus)
        max_df=0.95  # Ignore common words
    )
    X_tfidf = vectorizer.fit_transform(documents)

    # 2. Dimensionality Reduction (LSA) -> Dense Embeddings (e.g., 50 dims)
    n_components = min(50, len(documents) - 1)
    if n_components < 2:
        n_components = 2 # fallback
        
    svd = TruncatedSVD(n_components=n_components, random_state=42)
    X_dense = svd.fit_transform(X_tfidf)

    # 3. Visualization Coordinates (PCA -> 2D)
    # We can run PCA on the dense vectors
    pca = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(X_dense)

    # 4. Save to DB
    for i, company_id in enumerate(company_ids):
        company = Company.objects.get(id=company_id)
        vector_list = X_dense[i].tolist()
        
        CompanyEmbedding.objects.update_or_create(
            company=company,
            defaults={
                'vector': vector_list,
                'embedding_method': 'tfidf_svd',
                'pca_x': coords[i][0],
                'pca_y': coords[i][1],
                'created_at': timezone.now()
            }
        )
        
    return True, f"Processed {len(documents)} companies."
