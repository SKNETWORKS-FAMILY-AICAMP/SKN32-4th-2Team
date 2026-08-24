"""주제 분류 / 채팅방 이름 / 헬스체크 라우터."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.domain import TOPIC_CATEGORIES, TOPIC_MAX_LEN
from app.providers.registry import SUPPORTED, is_available
from app.schemas import (
    ERROR_RESPONSES,
    ChatroomNameRequest,
    ChatroomNameResponse,
    HealthResponse,
    TopicRequest,
    TopicResponse,
)
from app.services import rag_client
from app.services.naming import generate_name
from app.services.topic import classify

router = APIRouter(tags=["meta"])


@router.post(
    "/v1/topic",
    response_model=TopicResponse,
    responses=ERROR_RESPONSES,
    summary="[운영용] 주제 분류",
)
async def topic(req: TopicRequest) -> TopicResponse:
    """`chat.topic` 용. 항상 고정 카테고리 중 하나만 반환한다.

    **일반 대화 흐름에서는 쓰지 않는다.** `/v1/chat` 이 답변 생성과 주제 분류를
    동시에 돌려 응답에 실어 보내므로, 따로 부르면 LLM 호출만 한 번 더 나간다.

    남겨둔 용도는 일회성 배치 두 가지다.
    - 카테고리 목록이 바뀌었을 때 과거 chat 행 재분류
    - 발표 시연용 더미 데이터의 topic 채우기 (답변 생성 없이 분류만)
    """
    result, cached = await classify(req.message, req.source_files, req.provider)
    return TopicResponse(topic=result[:TOPIC_MAX_LEN], cached=cached)


@router.post(
    "/v1/chatroom-name",
    response_model=ChatroomNameResponse,
    responses=ERROR_RESPONSES,
    summary="채팅방 이름 생성",
)
async def chatroom_name(req: ChatroomNameRequest) -> ChatroomNameResponse:
    """`chatroom.chatroom_name` 용. 첫 질문으로 20자 내외 제목을 만든다.

    새 채팅방의 **첫 질문 때만** 호출한다. 두번째 질문부터는 부를 필요가 없다.
    LLM 호출이 실패해도 500 대신 질문 앞부분을 잘라 돌려주므로,
    채팅방 이름이 비는 일은 없다.
    """
    return ChatroomNameResponse(name=await generate_name(req.message, req.provider))


@router.get("/health", response_model=HealthResponse, summary="헬스체크")
async def health() -> HealthResponse:
    settings = get_settings()
    providers = {name: is_available(name) for name in SUPPORTED}
    return HealthResponse(
        status="ok" if any(providers.values()) else "degraded",
        providers=providers,
        default_provider=settings.default_provider,
        rag=await rag_client.health(),
        topic_categories=list(TOPIC_CATEGORIES),
    )
