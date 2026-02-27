from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse

from .models import Company, ScrapedData, CompanyEmbedding


def index(request):
    context = {
        'total_companies': Company.objects.count(),
        'scraped_count': ScrapedData.objects.count(),
        'embedded_count': CompanyEmbedding.objects.count(),
        'in_progress': Company.objects.filter(scrape_status='in_progress').count(),
        'recent_companies': Company.objects.order_by('-created_at')[:15],
    }
    return render(request, 'core/index.html', context)


def map_view(request):
    return render(request, 'core/map.html')


def search_view(request):
    return render(request, 'core/search.html')


def trigger_scraping(request):
    if request.method != 'POST':
        return redirect('index')

    limit = int(request.POST.get('limit', 500))
    from .tasks import scrape_pending_companies_task
    scrape_pending_companies_task.delay(limit=limit)
    messages.success(request, f'Scraping dispatched for up to {limit} companies.')
    return redirect('index')


def trigger_embedding(request):
    if request.method != 'POST':
        return redirect('index')

    from .tasks import full_pipeline_task
    full_pipeline_task.delay()
    messages.success(request, 'Embedding pipeline dispatched.')
    return redirect('index')


def api_map_data(request):
    data = list(
        CompanyEmbedding.objects.select_related('company')
        .filter(umap_x__isnull=False)
        .values_list(
            'company__id', 'company__name', 'company__url',
            'umap_x', 'umap_y',
            'company__industry', 'cluster_id', 'cluster_label',
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
    from pgvector.django import CosineDistance
    from .services.embeddings import embed_text

    query = request.GET.get('q', '').strip()
    n = int(request.GET.get('n', 20))
    n = max(1, min(n, 50))

    if not query:
        return JsonResponse({'error': 'Missing query parameter q'}, status=400)

    query_vector = embed_text(query).tolist()

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
