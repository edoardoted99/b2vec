from django.urls import path
from . import views

urlpatterns = [
    path('', views.chat_view, name='index'),
    path('map/', views.map_view, name='map_view'),
    path('search/', views.search_view, name='search_view'),
    path('company/<str:token>/', views.company_detail_view, name='company_detail'),
    path('atlas/', views.atlas_view, name='atlas_view'),
    path('api/atlas-data/', views.api_atlas_data, name='api_atlas_data'),
    path('exports/<str:filename>', views.serve_export, name='serve_export'),
    path('api/chat/', views.api_chat, name='api_chat'),
    path('api/map-data/', views.api_map_data, name='api_map_data'),
    path('api/similar/<str:token>/', views.api_similar_companies, name='api_similar_companies'),
    path('api/search/', views.api_semantic_search, name='api_semantic_search'),
    path('api/text-search/', views.api_text_search, name='api_text_search'),
    path('api/company/<str:token>/', views.api_company_detail, name='api_company_detail'),
]
