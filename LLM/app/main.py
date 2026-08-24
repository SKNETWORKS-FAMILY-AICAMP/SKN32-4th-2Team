"""Smart HR — LLM 서비스 (port 8002).

시퀀스다이어그램(PPT 17p) 상 위치:
    웹 프론트엔드 → 챗봇 서버(8000) → [LLM 서비스(8002)] → RAG 서비스(8001)

이 서비스는 DB에 쓰지 않는다. 답변/주제/근거를 JSON으로 돌려주기만 하고,
`chat` / `chatroom` 테이블 저장은 챗봇 서버가 담당한다.
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.errors import LLMServiceError
from app.providers import registry
from app.routers import chat, meta
from app.services import rag_client

# 한국어 Windows 는 콘솔 기본 인코딩이 cp949 라, 로그를 파일로 리다이렉트한 뒤
# UTF-8 로 읽으면 한글이 깨진다. 출력 스트림을 UTF-8 로 고정한다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("llm.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 프로바이더 생성(SDK import + HTTP 클라이언트 구성)은 실측 1.5~2.4초다.
    # 여기서 미리 만들어 두지 않으면 서버 기동 후 첫 사용자가 그 시간을 대신 문다.
    started = time.perf_counter()
    ready = registry.warm_up()
    rag_client.get_client()  # httpx 커넥션 풀도 같이 준비
    await registry.preconnect_all()  # 벤더 API TLS 연결까지 미리 열어둔다
    logger.info(
        "기동 준비 완료 %.0fms · 프로바이더 %s",
        (time.perf_counter() - started) * 1000,
        {k: ("ok" if v else "skip") for k, v in ready.items()},
    )

    yield
    await rag_client.close_client()


app = FastAPI(
    title="Smart HR — LLM 서비스",
    description=(
        "사내 HR 규정 질의응답용 LLM 서비스. "
        "답변 생성 / 주제 분류 / 채팅방 이름 생성을 제공한다.\n\n"
        "자세한 계약은 `LLM/docs/API.md` 참조."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# 챗봇 서버(8000)가 서버사이드로 호출하는 구조라 CORS 가 꼭 필요하진 않지만,
# 개발 중 프론트에서 직접 찔러볼 수 있게 열어둔다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(meta.router)


@app.exception_handler(LLMServiceError)
async def llm_error_handler(request: Request, exc: LLMServiceError) -> JSONResponse:
    """모든 서비스 예외를 docs/API.md 의 에러 규약 형태로 통일한다."""
    headers = {}
    # 한도 초과는 '기다리면 풀리는' 실패다. 얼마나 기다려야 하는지 알려주면
    # 호출자가 무작정 재시도하지 않고 그만큼 쉬었다 올 수 있다.
    retry_after = getattr(exc, "retry_after", None)
    if retry_after:
        headers["Retry-After"] = str(int(retry_after) + 1)

    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message},
        headers=headers or None,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "INVALID_REQUEST",
            "message": "요청 형식이 올바르지 않습니다.",
        },
    )


if __name__ == "__main__":
    # `python -m app.main` 으로 띄우면 .env 의 LLM_SERVICE_PORT 를 그대로 쓴다.
    # (uvicorn CLI 로 띄울 때는 --port 값이 우선한다)
    import uvicorn

    from app.config import get_settings

    uvicorn.run(app, host="0.0.0.0", port=get_settings().llm_service_port)
