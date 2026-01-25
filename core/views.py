from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from .models import Company, ScrapedData, CompanyEmbedding
from .services.scraper import scrape_website
from .services.embeddings import generate_embeddings
import json

def index(request):
    companies = Company.objects.all().order_by('-created_at')
    context = {
        'companies': companies,
        'total_companies': companies.count(),
        'scraped_count': ScrapedData.objects.count(),
        'embedded_count': CompanyEmbedding.objects.count(),
    }
    return render(request, 'core/index.html', context)

def add_company(request):
    if request.method == "POST":
        urls = request.POST.get('urls', '').splitlines()
        count = 0
        for line in urls:
            line = line.strip()
            if line:
                if not line.startswith('http'):
                    line = 'https://' + line
                # Basic name extraction (can be edited later)
                name = line.replace('https://', '').replace('http://', '').replace('www.', '').split('.')[0].capitalize()
                
                _, created = Company.objects.get_or_create(url=line, defaults={'name': name})
                if created:
                    count += 1
        messages.success(request, f"Added {count} new companies.")
    return redirect('index')

def trigger_scraping(request):
    companies = Company.objects.all()
    count = 0
    errors = 0
    for company in companies:
        # Check if scraped data exists using the manager
        if not company.scraped_data.exists():
            success, msg = scrape_website(company)
            if success:
                count += 1
            else:
                errors += 1
    
    if count == 0 and errors == 0:
        messages.info(request, "All companies already scraped.")
    else:
        messages.success(request, f"Scraped {count} companies. {errors} errors.")
    return redirect('index')

def trigger_embedding(request):
    success, msg = generate_embeddings()
    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect('index')

def map_view(request):
    return render(request, 'core/map.html')

def map_data(request):
    embeddings = CompanyEmbedding.objects.select_related('company').all()
    data = []
    for emb in embeddings:
        data.append({
            'name': emb.company.name,
            'url': emb.company.url,
            'x': emb.pca_x,
            'y': emb.pca_y,
            'industry': emb.company.industry or "Unknown"
        })
    return JsonResponse({'companies': data})
