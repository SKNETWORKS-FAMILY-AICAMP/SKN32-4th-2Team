from django.urls import path
from . import admin_views

urlpatterns = [
    path('', admin_views.users_page, name='users_page'),
    path('api/list', admin_views.list_users_api, name='list_users_api'),
    path('api/create', admin_views.create_user_api, name='create_user_api'),
    path('api/<str:user_id>/update', admin_views.update_user_api, name='update_user_api'),
    path('api/<str:user_id>/delete', admin_views.delete_user_api, name='delete_user_api'),
]
