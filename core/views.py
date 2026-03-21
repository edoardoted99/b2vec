import json
import logging
import re
from pathlib import Path

from django.conf import settings
from django.db.models import Count
from django.shortcuts import render, get_object_or_404
from django.http import FileResponse, Http404, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .id_cipher import encode_id, decode_id
from .models import Company, ScrapedData, CompanyEmbedding, CompanyProperties

logger = logging.getLogger(__name__)


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


def company_detail_view(request, token):
    company_id = decode_id(token)
    company = get_object_or_404(Company, id=company_id)
    properties = CompanyProperties.objects.filter(company=company).first()
    has_embedding = CompanyEmbedding.objects.filter(company=company).exists()
    context = {
        'company': company,
        'properties': properties,
        'has_embedding': has_embedding,
        'token': token,
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
            'id': encode_id(row[0]),
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


def api_similar_companies(request, token):
    from pgvector.django import CosineDistance

    company_id = decode_id(token)
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
            'id': encode_id(emb.company.id),
            'name': emb.company.name,
            'url': emb.company.url,
            'industry': emb.company.industry or 'Unknown',
            'similarity': round((1 - emb.distance) * 100, 1),
        }
        for emb in results
    ]

    company = target.company
    return JsonResponse({
        'company': {'id': encode_id(company.id), 'name': company.name},
        'similar': similar,
    })


def api_text_search(request):
    query = request.GET.get('q', '').strip()
    n = int(request.GET.get('n', 20))
    n = max(1, min(n, 50))

    if not query:
        return JsonResponse({'error': 'Missing query parameter q'}, status=400)

    from django.db.models import Q, Value, IntegerField, Case, When

    results = (
        Company.objects
        .filter(
            Q(name__icontains=query) |
            Q(url__icontains=query) |
            Q(website__icontains=query)
        )
        .annotate(
            rank=Case(
                When(name__iexact=query, then=Value(0)),
                When(name__istartswith=query, then=Value(1)),
                When(name__icontains=query, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        .order_by('rank', 'name')[:n]
    )

    companies = [
        {
            'id': encode_id(c.id),
            'name': c.name,
            'url': c.url,
            'industry': c.industry or 'Unknown',
        }
        for c in results
    ]

    return JsonResponse({'query': query, 'results': companies})


def api_semantic_search(request):
    import requests as http_requests
    from pgvector.django import CosineDistance

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
            'id': encode_id(emb.company.id),
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
        'ids': [encode_id(row[0]) for row in data],
    }
    return JsonResponse(result)


def api_company_detail(request, token):
    company_id = decode_id(token)
    company = get_object_or_404(Company, id=company_id)
    scraped = company.scraped_data.first()
    embedding = getattr(company, 'embedding', None)
    props = getattr(company, 'properties', None)

    data = {
        'id': encode_id(company.id),
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
        'properties': {
            'description': props.description,
            'phone': props.phone,
            'email': props.email,
            'vat_number': props.vat_number,
            'address': props.address,
            'services': props.services,
            'linkedin': props.linkedin,
            'facebook': props.facebook,
            'instagram': props.instagram,
        } if props else None,
    }
    return JsonResponse(data)


def serve_export(request, filename):
    if not re.fullmatch(r'[A-Za-z0-9_]+\.csv', filename):
        raise Http404
    filepath = Path(settings.BASE_DIR) / 'exports' / filename
    if not filepath.is_file():
        raise Http404
    return FileResponse(
        open(filepath, 'rb'),
        content_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


def api_stats(request):
    from .services.chat import _exec_get_stats
    return JsonResponse(_exec_get_stats())


@require_POST
def api_sql(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    query = body.get('query', '').strip()
    if not query:
        return JsonResponse({'error': 'Missing query'}, status=400)
    from .services.chat import _exec_run_sql
    return JsonResponse(_exec_run_sql(query))


@ensure_csrf_cookie
def chat_view(request):
    return render(request, 'core/chat.html')


@require_POST
def api_chat(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    messages = body.get('messages')
    if not messages or not isinstance(messages, list):
        return JsonResponse({'error': 'Missing messages array'}, status=400)

    # Sanitize: only keep role and content from client messages
    clean = []
    for m in messages:
        role = m.get('role')
        content = m.get('content', '')
        if role in ('user', 'assistant') and isinstance(content, str):
            clean.append({'role': role, 'content': content})

    if not clean:
        return JsonResponse({'error': 'No valid messages'}, status=400)

    from .services.chat import chat_stream

    def event_stream():
        try:
            for event_type, data in chat_stream(clean):
                payload = json.dumps(
                    {'content': data} if event_type == 'token' else data,
                    ensure_ascii=False, default=str,
                )
                yield f"event: {event_type}\ndata: {payload}\n\n"
        except Exception:
            logger.exception('Chat stream error')
            yield f"event: error\ndata: {json.dumps({'error': 'Internal error. Please try again.'})}\n\n"

    resp = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    resp['Cache-Control'] = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    return resp
