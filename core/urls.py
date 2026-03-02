from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('map/', views.map_view, name='map_view'),
    path('search/', views.search_view, name='search_view'),
    path('company/<int:company_id>/', views.company_detail_view, name='company_detail'),
    path('api/map-data/', views.api_map_data, name='api_map_data'),
    path('api/similar/<int:company_id>/', views.api_similar_companies, name='api_similar_companies'),
    path('api/search/', views.api_semantic_search, name='api_semantic_search'),
    path('api/company/<int:company_id>/', views.api_company_detail, name='api_company_detail'),
]
