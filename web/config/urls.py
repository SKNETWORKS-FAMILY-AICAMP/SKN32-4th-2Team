"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from users.views import post_login_redirect_url


def root_redirect(request):
    """로그인 안 됐으면 로그인 화면으로, 로그인 됐으면 관리자는 /admin/stats로,
    일반 유저는 /chat으로 보낸다."""
    if request.user.is_authenticated:
        return redirect(post_login_redirect_url(request.user.is_admin))
    return redirect('/login')


urlpatterns = [
    path("", root_redirect, name="root"),

    path("login/", include('users.urls')),
    path("chat/", include('chat.urls')),

    # 우리 서비스 관리자 페이지
    path("admin/users/", include('users.admin_urls')),
    path("admin/documents/", include('users.document_urls')),
    path("admin/stats/", include('users.stats_urls')),

    # Django 기본 관리자
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
