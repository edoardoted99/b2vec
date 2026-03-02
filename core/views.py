from django.db.models import Count
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse

from .models import Company, ScrapedData, CompanyEmbedding, CompanyProperties


def index(request):
    top_industries = (
        Company.objects
        .filter(industry__isnull=False)
        .exclude(industry='')
        .values('industry')
        .annotate(count=Count('id'))
        .order_by('-count')[:12]
    )
    context = {
        'total_companies': Company.objects.count(),
        'scraped_count': ScrapedData.objects.count(),
        'embedded_count': CompanyEmbedding.objects.count(),
        'properties_count': CompanyProperties.objects.count(),
        'top_industries': top_industries,
    }
    return render(request, 'core/index.html', context)


def map_view(request):
    return render(request, 'core/map.html')


def search_view(request):
    return render(request, 'core/search.html')


def company_detail_view(request, company_id):
    company = get_object_or_404(Company, id=company_id)
    properties = getattr(company, 'properties', None)
    embedding = getattr(company, 'embedding', None)
    context = {
        'company': company,
        'properties': properties,
        'has_embedding': embedding is not None,
    }
    return render(request, 'core/company_detail.html', context)



def api_map_data(request):
    from django.db.models import OuterRef, Subquery
    desc_subquery = CompanyProperties.objects.filter(
        company_id=OuterRef('company_id')
    ).values('description')[:1]

    data = list(
        CompanyEmbedding.objects.select_related('company')
        .filter(umap_x__isnull=False)
        .annotate(description=Subquery(desc_subquery))
        .values_list(
            'company__id', 'company__name', 'company__url',
            'umap_x', 'umap_y',
            'company__industry', 'cluster_id', 'cluster_label',
            'description',
        )
    )
    companies = [
        {
            'id': row[0],
            'name': row[1],
            'url': row[2],
            'x': row[3],
            'y': row[4],
            'industry': row[5] or 'Unknown',
            'cluster_id': row[6],
            'cluster_label': row[7] or 'Unknown',
            'description': row[8] or '',
        }
        for row in data
    ]
    return JsonResponse({'companies': companies})


def api_similar_companies(request, company_id):
    from pgvector.django import CosineDistance

    n = int(request.GET.get('n', 10))
    n = max(1, min(n, 50))

    target = get_object_or_404(CompanyEmbedding, company_id=company_id)

    results = (
        CompanyEmbedding.objects
        .exclude(company_id=company_id)
        .annotate(distance=CosineDistance('vector', target.vector))
        .order_by('distance')
        .select_related('company')[:n]
    )

    similar = [
        {
            'id': emb.company.id,
            'name': emb.company.name,
            'url': emb.company.url,
            'industry': emb.company.industry or 'Unknown',
            'similarity': round((1 - emb.distance) * 100, 1),
        }
        for emb in results
    ]

    company = target.company
    return JsonResponse({
        'company': {'id': company.id, 'name': company.name},
        'similar': similar,
    })


def api_semantic_search(request):
    import requests as http_requests
    from pgvector.django import CosineDistance
    from django.conf import settings

    query = request.GET.get('q', '').strip()
    n = int(request.GET.get('n', 20))
    n = max(1, min(n, 50))

    if not query:
        return JsonResponse({'error': 'Missing query parameter q'}, status=400)

    resp = http_requests.post(
        f"{settings.OLLAMA_BASE_URL}/api/embed",
        json={"model": settings.OLLAMA_EMBED_MODEL, "input": query},
        timeout=30,
    )
    resp.raise_for_status()
    query_vector = resp.json()["embeddings"][0]

    results = (
        CompanyEmbedding.objects
        .annotate(distance=CosineDistance('vector', query_vector))
        .order_by('distance')
        .select_related('company')[:n]
    )

    companies = [
        {
            'id': emb.company.id,
            'name': emb.company.name,
            'url': emb.company.url,
            'industry': emb.company.industry or 'Unknown',
            'similarity': round((1 - emb.distance) * 100, 1),
            'x': emb.umap_x,
            'y': emb.umap_y,
        }
        for emb in results
    ]

    return JsonResponse({'query': query, 'results': companies})


def atlas_view(request):
    return render(request, 'core/atlas.html')


def api_atlas_data(request):
    from django.db.models import OuterRef, Subquery

    desc_subquery = CompanyProperties.objects.filter(
        company_id=OuterRef('company_id')
    ).values('description')[:1]

    data = list(
        CompanyEmbedding.objects.select_related('company')
        .filter(umap_x__isnull=False)
        .annotate(description=Subquery(desc_subquery))
        .values_list(
            'company__id', 'company__name',
            'umap_x', 'umap_y',
            'company__industry', 'cluster_id', 'cluster_label',
        )
    )

    # Build unique cluster label mapping: cluster_id -> index
    unique_labels = {}
    for row in data:
        cid = row[5]
        if cid is not None and cid not in unique_labels:
            unique_labels[cid] = row[6] or 'Unknown'

    # Sort by cluster_id for consistent ordering
    sorted_cids = sorted(unique_labels.keys())
    cid_to_index = {cid: i for i, cid in enumerate(sorted_cids)}
    category_labels = [unique_labels[cid] for cid in sorted_cids]

    result = {
        'x': [row[2] for row in data],
        'y': [row[3] for row in data],
        'categories': [cid_to_index.get(row[5], 0) for row in data],
        'categoryLabels': category_labels,
        'names': [row[1] or '' for row in data],
        'industries': [row[4] or 'Unknown' for row in data],
        'ids': [row[0] for row in data],
    }
    return JsonResponse(result)


def api_company_detail(request, company_id):
    company = get_object_or_404(Company, id=company_id)
    scraped = company.scraped_data.first()
    embedding = getattr(company, 'embedding', None)

    data = {
        'id': company.id,
        'name': company.name,
        'url': company.url,
        'website': company.website,
        'industry': company.industry,
        'size': company.size,
        'type': company.type,
        'founded': company.founded,
        'city': company.city,
        'state': company.state,
        'country_code': company.country_code,
        'scrape_status': company.scrape_status,
        'has_scraped_data': scraped is not None,
        'has_embedding': embedding is not None,
        'cluster_id': embedding.cluster_id if embedding else None,
        'cluster_label': embedding.cluster_label if embedding else None,
    }
    return JsonResponse(data)
