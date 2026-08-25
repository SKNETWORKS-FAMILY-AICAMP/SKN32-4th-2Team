from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_page, name='login'),
    path('auth/login', views.login_submit, name='login_submit'),
    path('auth/check-user-id', views.check_user_id, name='check_user_id'),
    path('auth/signup', views.signup_submit, name='signup_submit'),
    path('auth/logout', views.logout_submit, name='logout_submit'),
]
