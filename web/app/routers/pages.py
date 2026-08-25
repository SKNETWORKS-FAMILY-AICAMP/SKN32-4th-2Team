from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..core.security import post_login_redirect_url, require_login

router = APIRouter(tags=["Pages"])


@router.get("/", response_class=HTMLResponse)
def root(request: Request):
    """로그인 안 됐으면 로그인 화면으로, 로그인 됐으면 관리자는 /admin/stats로,
    일반 유저는 /chat으로 보낸다. (예전엔 /main을 거쳐 리다이렉트가 두 번 걸렸는데,
    /main 자체를 없애고 여기서 바로 최종 목적지로 보내도록 정리했다.)"""
    user, redirect = require_login(request)
    if redirect:
        return redirect

    return RedirectResponse(
        url=post_login_redirect_url(user.get("is_admin")), status_code=303
    )
