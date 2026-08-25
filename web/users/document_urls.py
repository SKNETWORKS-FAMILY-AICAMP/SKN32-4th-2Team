from django.urls import path
from . import document_views

urlpatterns = [
    path('', document_views.documents_page, name='documents_page'),
]
