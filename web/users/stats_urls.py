from django.urls import path
from . import stats_views

urlpatterns = [
    path('', stats_views.stats_page, name='stats_page'),
    path('api/summary', stats_views.stats_summary_api, name='stats_summary_api'),
]
