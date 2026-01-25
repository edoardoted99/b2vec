from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('add/', views.add_company, name='add_company'),
    path('scrape/', views.trigger_scraping, name='trigger_scraping'),
    path('embed/', views.trigger_embedding, name='trigger_embedding'),
    path('map/', views.map_view, name='map_view'),
    path('api/map-data/', views.map_data, name='map_data'),
]
