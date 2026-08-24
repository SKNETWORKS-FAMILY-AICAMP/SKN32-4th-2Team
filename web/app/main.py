import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .core.database import warm_up as warm_up_db
from .core.security import SESSION_MAX_AGE_SECONDS
from .routers.pages import router as pages_router
from .routers.auth import router as auth_router
from .routers.admin.user_router import router as users_router
from .routers.admin.document_router import router as documents_router
from .routers.admin.stats_router import router as stats_router
from .routers.chat.chat_router import router as chat_router
from .services.llm_client import ChatAPIError, warm_up as warm_up_chat_api

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB는 로그인을 포함한 거의 모든 기능이 의존하는 필수 자원이라, 여기서 실패하면
    # 예외를 그대로 올려서 서버 기동 자체를 실패시킨다 (조용히 넘어가면 첫 요청에서야
    # DB가 안 된다는 걸 알게 되므로, 기동 시점에 바로 아는 게 낫다).
    warm_up_db()

    # Chat API httpx.Client를 미리 만들어둔다. 여기서 못 만들어도(CHAT_API_BASE_URL 미설정 등)
    # 서버 자체는 정상적으로 떠야 하므로 조용히 넘어간다 - 실제 호출 시점에 다시 시도된다.
    try:
        warm_up_chat_api()
    except ChatAPIError:
        pass

    yield


app = FastAPI(title="RAG 챗봇", lifespan=lifespan)

# NOTE:
# 쿠키 max_age는 실제 세션 만료 시간(SESSION_MAX_AGE_SECONDS, 3시간)보다 길게 설정한다.
# 동일하게 설정하면 세션 만료 시 브라우저가 쿠키를 제거하여,
# "세션 만료"와 "로그인 이력 없음"을 구분할 수 없게 된다.
# (core/security.py의 _had_session_cookie에서 구분 용도로 사용)
#
# 실제 인증 유효성은 core/security.py에서 세션의 login_at 기준으로 판단하므로,
# 쿠키 수명을 늘려도 로그인 유지 시간이 늘어나지는 않는다.
SESSION_COOKIE_MAX_AGE_SECONDS = SESSION_MAX_AGE_SECONDS + 7 * 24 * 60 * 60  # 세션 유효시간 + 7일 여유

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY", "dev-secret-change-me"),
    max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
    same_site="lax",
)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
app.include_router(pages_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(stats_router)
app.include_router(documents_router)
app.include_router(chat_router)
