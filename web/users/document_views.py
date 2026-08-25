from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings


def is_admin(user):
    return user.is_authenticated and user.is_admin


@login_required
@user_passes_test(is_admin, login_url='/login')
def documents_page(request):
    """문서 관리 페이지 셸��� 렌더링한다. 파일 목록/업로드/적재 등 실제 동작은
    static/js/rag.js가 DOC_API_BASE_URL을 대상으로 직접 호출해서 처리한다."""
    doc_api_base_url = getattr(settings, 'DOC_API_BASE_URL', '')
    
    return render(request, 'admin/documents.html', {
        'user': request.user,
        'active': 'admin_docs',
        'doc_api_base_url': doc_api_base_url,
    })
