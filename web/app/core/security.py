import os
import time

import bcrypt
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

# 세션 유효 시간: 3시간
SESSION_MAX_AGE_SECONDS = int(os.getenv("SESSION_MAX_AGE_SECONDS", str(3 * 60 * 60)))


def hash_password(raw_password: str) -> str:
    hashed = bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(raw_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(raw_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_session(request: Request, user_id: str, name: str, is_admin: bool) -> None:
    request.session["user_id"] = user_id
    request.session["name"] = name
    request.session["is_admin"] = is_admin
    request.session["login_at"] = time.time()


def clear_session(request: Request) -> None:
    request.session.clear()


def get_current_user(request: Request):
    """세션에 로그인 정보가 있고, 3시간 이내라면 사용자 정보를 반환한다.
    없거나 만료되었으면 None을 반환한다."""
    user_id = request.session.get("user_id")
    login_at = request.session.get("login_at")

    if not user_id or not login_at:
        return None

    if time.time() - login_at > SESSION_MAX_AGE_SECONDS:
        request.session.clear()
        return None

    return {
        "user_id": user_id,
        "name": request.session.get("name"),
        "is_admin": request.session.get("is_admin", False),
    }


def _had_session_cookie(request: Request) -> bool:
    """세션이 "있다가 만료된 것"과 "처음부터 없던 것"을 구분하기 위한 판단 기준.

    주의:
    SessionMiddleware(Starlette)는 max_age가 지난 세션 쿠키를 처리하는 과정에서
    세션 데이터를 유효하지 않은 것으로 판단하고, 라우트 코드가 실행되기 전에
    request.session을 빈 상태로 만든다.

    따라서 request.session.get("login_at") 같은 세션 내부 값만 확인하면,
    "기존 세션이 만료된 경우"와 "로그인한 적이 없는 경우"를 구분할 수 없다.

    이를 구분하기 위해 디코딩된 session 데이터가 아니라,
    요청에 포함된 원본 세션 쿠키의 존재 여부를 확인한다.

    - 세션 쿠키가 존재하지만 session 데이터가 비어 있음 → 기존 세션 만료
    - 세션 쿠키 자체가 없음 → 로그인 이력 없음
    """
    return bool(request.cookies.get("session"))


def require_login(request: Request):
    """페이지 접근 시 로그인 여부를 검사하는 라우트 보호용 함수.

    인증 세션이 없으면 로그인 페이지로 리다이렉트한다.
    단, 이전에 로그인한 세션이 만료된 경우에는 /login?expired=1을 사용해
    세션 만료 상태를 전달한다.

    로그인 화면은 이 값을 기준으로 일반 로그인 안내와
    "세션이 만료되어 다시 로그인해야 함"을 구분해 표시한다.
    """
    had_session = _had_session_cookie(request)
    user = get_current_user(request)
    if user is None:
        login_url = "/login?expired=1" if had_session else "/login"
        return None, RedirectResponse(url=login_url, status_code=303)
    return user, None


def require_login_api(request: Request):
    """API 라우트에서 로그인 여부를 검사하고, 미로그인 시 401을 반환한다."""
    user = get_current_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다."
        )

    return user


def post_login_redirect_url(is_admin: bool) -> str:
    """로그인 직후(또는 이미 로그인된 상태로 /login에 온 경우) 보낼 목적지.
    관리자는 챗봇을 쓰지 않으므로 통계 화면으로, 일반 유저는 채팅 화면으로 보낸다.
    /main을 거쳐 다시 리다이렉트되던 걸 없애기 위해 이 함수로 최종 목적지를 바로 계산한다.
    세션 dict({"is_admin": ...})든 User 모델(.is_admin)이든 호출부에서 bool만 뽑아 넘기면 된다."""
    return "/admin/stats" if is_admin else "/chat"


def require_admin(request: Request):
    """관리자 전용 페이지 라우트에서 로그인 및 관리자 권한을 검사한다.
    미로그인 시 로그인 화면으로(세션 만료였다면 ?expired=1과 함께), 관리자가 아니면 채팅 화면으로 리다이렉트한다."""
    had_session = _had_session_cookie(request)
    user = get_current_user(request)
    if user is None:
        login_url = "/login?expired=1" if had_session else "/login"
        return None, RedirectResponse(url=login_url, status_code=303)
    if not user.get("is_admin"):
        return None, RedirectResponse(
            url=post_login_redirect_url(False), status_code=303
        )
    return user, None


def require_admin_api(request: Request):
    """관리자 전용 API 라우트에서 로그인 및 관리자 권한을 검사한다.
    미로그인 시 401, 관리자가 아니면 403을 반환한다."""
    user = require_login_api(request)
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="관리자만 접근할 수 있습니다."
        )
    return user
