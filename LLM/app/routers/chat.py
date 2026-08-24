"""챗봇 응답 라우터."""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas import ERROR_RESPONSES, ChatRequest, ChatResponse
from app.services.answer import generate_answer, stream_answer

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses=ERROR_RESPONSES,
    summary="답변 생성",
)
async def chat(req: ChatRequest) -> ChatResponse:
    """질문에 대한 답변 + 근거 문서 + 주제를 한 번에 반환한다.

    RAG 검색에 실패해도 500이 아니라 `rag_degraded: true` 로 200 응답한다.
    """
    return await generate_answer(req)


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/stream", summary="[미사용] 답변 생성 (SSE 스트리밍)")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """`sources` → `token`* → `done` 순서로 흘려보낸다. 실패 시 `error`.

    1차 구현에서는 쓰지 않는다. WEB 파트는 `/v1/chat` 만 사용하기로 합의했고,
    나중에 타이핑 효과가 필요해지면 붙인다. Request 형식이 `/v1/chat` 과
    동일하므로 그때 요청 코드는 그대로 두면 된다.
    """

    async def event_source():
        async for event, payload in stream_answer(req):
            yield _sse(event, payload)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
