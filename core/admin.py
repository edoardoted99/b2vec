from django.contrib import admin
from .models import Company, ScrapedData, CompanyEmbedding

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'created_at')
    search_fields = ('name', 'url')

@admin.register(ScrapedData)
class ScrapedDataAdmin(admin.ModelAdmin):
    list_display = ('company', 'scraped_at')
    raw_id_fields = ('company',)

@admin.register(CompanyEmbedding)
class CompanyEmbeddingAdmin(admin.ModelAdmin):
    list_display = ('company', 'embedding_method', 'pca_x', 'pca_y', 'created_at')
    raw_id_fields = ('company',)
