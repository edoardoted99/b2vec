from django.contrib import admin
from .models import Company, ScrapedData, CompanyEmbedding


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'industry', 'country_code', 'scrape_status', 'created_at')
    list_filter = ('scrape_status', 'industry', 'country_code')
    search_fields = ('name', 'handle', 'url', 'website')


@admin.register(ScrapedData)
class ScrapedDataAdmin(admin.ModelAdmin):
    list_display = ('company', 'scraped_at')
    raw_id_fields = ('company',)


@admin.register(CompanyEmbedding)
class CompanyEmbeddingAdmin(admin.ModelAdmin):
    list_display = ('company', 'cluster_id', 'cluster_label', 'umap_x', 'umap_y', 'created_at')
    list_filter = ('cluster_label',)
    raw_id_fields = ('company',)
