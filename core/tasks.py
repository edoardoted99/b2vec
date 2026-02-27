import logging

from celery import shared_task
from django.db.models import Count

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def scrape_company_task(self, company_id):
    """Scrape a single company."""
    from core.models import Company
    from core.services.scraper import scrape_company

    try:
        company = Company.objects.get(id=company_id)
        success, msg = scrape_company(company)
        return {'company_id': company_id, 'success': success, 'message': msg}
    except Company.DoesNotExist:
        return {'company_id': company_id, 'success': False, 'message': 'Not found'}
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def scrape_pending_companies_task(limit=500):
    """Dispatch individual scrape tasks for pending companies."""
    from core.models import Company

    companies = Company.objects.filter(
        scrape_status='pending'
    ).values_list('id', flat=True)[:limit]

    count = 0
    for company_id in companies:
        scrape_company_task.delay(company_id)
        count += 1

    return {'dispatched': count}


@shared_task
def generate_embeddings_task(company_ids=None):
    """Generate SBERT embeddings for companies with scraped data."""
    import numpy as np
    from core.models import Company, ScrapedData, CompanyEmbedding
    from core.services.embeddings import embed_texts_batch

    qs = ScrapedData.objects.select_related('company')
    if company_ids:
        qs = qs.filter(company_id__in=company_ids)

    items = list(qs.filter(text_content__isnull=False))
    items = [item for item in items if len(item.text_content) > 50]

    if not items:
        return {'processed': 0, 'message': 'No data to embed'}

    texts = [item.text_content for item in items]
    vectors = embed_texts_batch(texts)

    objs_to_create = []
    objs_to_update = []

    existing = set(
        CompanyEmbedding.objects.filter(
            company_id__in=[item.company_id for item in items]
        ).values_list('company_id', flat=True)
    )

    for i, item in enumerate(items):
        vec = vectors[i].tolist()
        if item.company_id in existing:
            emb = CompanyEmbedding.objects.get(company_id=item.company_id)
            emb.vector = vec
            objs_to_update.append(emb)
        else:
            objs_to_create.append(CompanyEmbedding(
                company_id=item.company_id,
                vector=vec,
            ))

    if objs_to_create:
        CompanyEmbedding.objects.bulk_create(objs_to_create)
    if objs_to_update:
        CompanyEmbedding.objects.bulk_update(objs_to_update, ['vector'])

    return {'processed': len(items)}


@shared_task
def compute_projections_task():
    """Compute UMAP projections and HDBSCAN clusters, then update DB."""
    import numpy as np
    from core.models import CompanyEmbedding
    from core.services.embeddings import compute_umap_projection, compute_hdbscan_clusters

    embeddings = list(CompanyEmbedding.objects.select_related('company').all())
    if len(embeddings) < 3:
        return {'message': 'Not enough embeddings for projection'}

    vectors = np.array([emb.vector for emb in embeddings])

    coords = compute_umap_projection(vectors)
    labels = compute_hdbscan_clusters(coords)

    # Build cluster label from most common industry per cluster
    from collections import Counter
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

    for i, emb in enumerate(embeddings):
        emb.umap_x = float(coords[i][0])
        emb.umap_y = float(coords[i][1])
        emb.cluster_id = int(labels[i])
        emb.cluster_label = cluster_labels.get(int(labels[i]), 'Noise')

    CompanyEmbedding.objects.bulk_update(
        embeddings, ['umap_x', 'umap_y', 'cluster_id', 'cluster_label']
    )

    return {'updated': len(embeddings), 'clusters': len(cluster_labels)}


@shared_task
def full_pipeline_task():
    """Run embeddings then projections sequentially."""
    result_embed = generate_embeddings_task()
    result_proj = compute_projections_task()
    return {
        'embeddings': result_embed,
        'projections': result_proj,
    }
