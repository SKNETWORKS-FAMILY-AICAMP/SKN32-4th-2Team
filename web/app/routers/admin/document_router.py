import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ...core.security import require_admin

router = APIRouter(
    prefix="/admin/documents",
    tags=["Admin Documents"],
)

# main.py와 동일한 절대경로 기준으로 템플릿을 로드한다.
BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# 문서 관리는 별도로 떠 있는 API 서버를 화면(rag.js)이 직접 호출한다 (우리 백엔드가
# 프록시하지 않음). .env에 주소가 없으면 기존 rag.js 기본값이던 상대경로 '/api'로
# 동작하도록 빈 문자열을 내려준다 (rag.js에서 `window.DOC_API_BASE_URL || '/api'`로 처리).
DOC_API_BASE_URL = os.getenv("DOC_API_BASE_URL", "")


@router.get("", response_class=HTMLResponse)
def documents_page(request: Request):
    """문서 관리 페이지 셸을 렌더링한다. 파일 목록/업로드/적재 등 실제 동작은
    static/js/rag.js가 DOC_API_BASE_URL을 대상으로 직접 호출해서 처리한다."""
    user, redirect = require_admin(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        request,
        "admin/documents.html",
        {
            "user": user,
            "active": "admin_docs",
            "doc_api_base_url": DOC_API_BASE_URL,
        },
    )
