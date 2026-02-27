from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('map/', views.map_view, name='map_view'),
    path('search/', views.search_view, name='search_view'),
    path('actions/scrape/', views.trigger_scraping, name='trigger_scraping'),
    path('actions/embed/', views.trigger_embedding, name='trigger_embedding'),
    path('api/map-data/', views.api_map_data, name='api_map_data'),
    path('api/similar/<int:company_id>/', views.api_similar_companies, name='api_similar_companies'),
    path('api/search/', views.api_semantic_search, name='api_semantic_search'),
    path('api/company/<int:company_id>/', views.api_company_detail, name='api_company_detail'),
]
