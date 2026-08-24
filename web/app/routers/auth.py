import os
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..core.security import (
    clear_session,
    create_session,
    get_current_user,
    hash_password,
    post_login_redirect_url,
    verify_password,
)
from ..core.database import get_db
from ..models import User
from ..services.user_service import record_login

router = APIRouter(tags=["Auth"])

# main.py와 동일한 절대경로 기준으로 템플릿을 로드한다.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

USER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{4,20}$")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url=post_login_redirect_url(user.get("is_admin")), status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/auth/login")
def login_submit(
    request: Request,
    user_id: str = Form(...),
    passwd: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)

    if user is None or user.is_deleted or not verify_password(passwd, user.passwd):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "아이디 또는 비밀번호가 올바르지 않습니다."},
            status_code=401,
        )

    if user.is_disabled:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "비활성화된 계정입니다. 관리자에게 문의하세요."},
            status_code=403,
        )

    create_session(request, user.user_id, user.name, user.is_admin)
    record_login(db, user.user_id)
    return RedirectResponse(url=post_login_redirect_url(user.is_admin), status_code=303)


@router.get("/auth/check-user-id")
def check_user_id(user_id: str, db: Session = Depends(get_db)):
    """회원가입/사용자추가 모달의 '중복확인' 버튼이 호출하는 엔드포인트."""
    if not USER_ID_PATTERN.match(user_id):
        return JSONResponse(
            status_code=400,
            content={"available": False, "detail": "아이디는 영문/숫자 4~20자로 입력해주세요."},
        )

    exists = db.get(User, user_id) is not None
    if exists:
        return {"available": False, "detail": "이미 사용 중인 아이디입니다."}

    return {"available": True, "detail": "사용 가능한 아이디입니다."}


@router.post("/auth/signup")
def signup_submit(
    request: Request,
    user_id: str = Form(...),
    passwd: str = Form(...),
    passwd_confirm: str = Form(...),
    name: str = Form(...),
    department: str = Form(...),
    db: Session = Depends(get_db),
):
    if not USER_ID_PATTERN.match(user_id):
        return JSONResponse(
            status_code=400,
            content={"detail": "아이디는 영문/숫자 4~20자로 입력해주세요."},
        )

    if len(passwd) < 8:
        return JSONResponse(
            status_code=400,
            content={"detail": "비밀번호는 8자 이상이어야 합니다."},
        )

    if passwd != passwd_confirm:
        return JSONResponse(
            status_code=400,
            content={"detail": "비밀번호가 일치하지 않습니다."},
        )

    if db.get(User, user_id) is not None:
        return JSONResponse(
            status_code=409,
            content={"detail": "이미 사용 중인 아이디입니다."},
        )

    new_user = User(
        user_id=user_id,
        passwd=hash_password(passwd),
        name=name,
        department=department,
        is_admin=False,
        is_disabled=False,
    )
    db.add(new_user)
    db.commit()

    return JSONResponse(status_code=201, content={"detail": "회원가입이 완료되었습니다. 로그인해주세요."})


@router.post("/auth/logout")
def logout(request: Request):
    clear_session(request)
    return RedirectResponse(url="/login", status_code=303)