import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ...core.security import require_admin, require_admin_api
from ...core.database import get_db
from ...services.user_service import (
    UserServiceError,
    create_user_by_admin,
    delete_user_by_admin,
    get_user_list_by_params,
    update_user_profile,
)

router = APIRouter(
    prefix="/admin/users",
    tags=["Admin Users"],
)

# main.py와 동일한 절대경로 기준으로 템플릿을 로드한다.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@router.get("", response_class=HTMLResponse)
def users_page(
    request: Request
):
    user, redirect = require_admin(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        request,
        "admin/users.html", {"user": user,"active": "admin_users"},
    )


@router.get("/api/list")
def list_users_api(
    request: Request,
    name: str | None = None,
    department: str | None = None,
    is_disabled: bool | None = None,
    is_admin: bool | None = None,
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
):
    require_admin_api(request)

    return get_user_list_by_params(
        db,
        name=name,
        department=department,
        is_disabled=is_disabled,
        is_admin=is_admin,
        page=page,
        size=size,
    )


@router.post("/api/create")
def create_user_api(
    request: Request,
    user_id: str = Form(...),
    passwd: str = Form(...),
    passwd_confirm: str = Form(...),
    name: str = Form(...),
    department: str = Form(...),
    is_admin: bool | None = Form(None),
    is_disabled: bool | None = Form(None),
    db: Session = Depends(get_db),
):
    """사용자 관리 화면의 '사용자 추가' 모달(회원가입 모달 재사용) 제출이 여기로 들어온다.
    공개 회원가입(/auth/signup)과 달리 관리자 권한이 있어야 호출 가능하다."""
    require_admin_api(request)

    try:
        create_user_by_admin(db, user_id, passwd, passwd_confirm, name, department, is_admin, is_disabled)
    except UserServiceError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.message})

    return JSONResponse(status_code=201, content={"detail": "사용자가 추가되었습니다."})


@router.patch("/api/{user_id}")
def update_user_api(
    request: Request,
    user_id: str,
    name: str = Form(None),
    department: str = Form(None),
    passwd: str = Form(None),
    is_admin: bool | None = Form(None),
    is_disabled: bool | None = Form(None),
    db: Session = Depends(get_db),
):
    """사용자 관리 테이블의 행을 클릭하면 뜨는 수정 모달 제출.
    이름/부서명/비밀번호/관리자권한/비활성여부를 변경할 수 있다."""
    admin = require_admin_api(request)

    try:
        update_user_profile(
            db,
            user_id,
            admin["user_id"],
            name=name,
            department=department,
            passwd=passwd,
            is_admin=is_admin,
            is_disabled=is_disabled,
        )
    except UserServiceError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.message})

    return JSONResponse(status_code=200, content={"detail": "수정되었습니다."})


@router.delete("/api/{user_id}")
def delete_user_api(request: Request, user_id: str, db: Session = Depends(get_db)):
    """사용자 관리 수정 모달의 '계정 삭제' 버튼. 본인 계정은 삭제할 수 없다."""
    admin = require_admin_api(request)

    try:
        delete_user_by_admin(db, user_id, admin["user_id"])
    except UserServiceError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.message})

    return JSONResponse(status_code=200, content={"detail": "계정이 삭제되었습니다."})