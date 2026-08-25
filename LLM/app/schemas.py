"""API 계약의 단일 출처.

여기 정의된 모델이 그대로 FastAPI 자동 문서(/docs)와 docs/API.md 가 된다.
챗봇 서버(Member B, port 8000)가 이 스키마에 맞춰 붙는다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.domain import TOPIC_CATEGORIES

# 서비스 API에서는 상용 프로바이더만 선택할 수 있다.
# Qwen 관련 코드는 별도 실험 및 벤치마크 트랙에 남기되 운영 요청으로는 받지 않는다.
ProviderName = Literal["openai", "gemini"]
Speaker = Literal["user", "llm"]


class HistoryTurn(BaseModel):
    """이전 대화 한 턴. `chat` 테이블 행과 1:1 대응."""

    speaker: Speaker
    message: str


class Source(BaseModel):
    """답변의 근거 문서. 스토리보드 13p '답변 하단 근거 문서명 노출'용.

    화면에 표시할 값만 담는다. 청크 본문과 유사도 점수는 서버 내부에서만 쓰고
    응답에는 싣지 않는다 (docs/API.md 1절 참조).
    """

    doc_id: int | None = Field(
        None,
        description="document.doc_id. 문서 원본 링크·다운로드에 쓴다. RAG가 알려주지 않으면 null",
    )
    original_file_name: str = Field(
        ..., description="document.original_file_name. 화면에 표시할 문서명"
    )
    page: int | None = Field(None, description='근거가 위치한 페이지. "복무규정.pdf p.5" 표시용')


class ChatRequest(BaseModel):
    chatroom_id: str = Field(
        ...,
        description=(
            "chatroom.chatroom_id (UUID). 답변 생성에는 쓰이지 않고 서버 로그에만 "
            "남지만, 특정 대화에서 문제가 생겼을 때 로그를 추려내려면 반드시 필요하므로 필수다."
        ),
    )
    message: str = Field(..., min_length=1, description="사용자 질문")
    history: list[HistoryTurn] = Field(
        default_factory=list,
        description=(
            "이전 대화. 최근 2~3턴만 보내면 된다(전체를 보낼 필요 없음). "
            "생략하거나 빈 배열로 두면 이 질문을 앞뒤 맥락 없는 독립 질문으로 처리한다. "
            "채워 보내면 '그럼 반차는?' 같은 후속 질문의 답변과 문서 검색이 함께 정확해진다. "
            "서버는 상태를 저장하지 않으므로, 필요한 맥락은 매 요청에 실어 보내야 한다."
        ),
    )
    # 아래 둘은 성능 비교·디버깅용 내부 스위치다. WEB 은 보내지 않으면 된다.
    provider: ProviderName | None = Field(
        None,
        description=(
            "[내부용] WEB 에서는 보내지 마세요. 미지정 시 서버 기본값(DEFAULT_PROVIDER) 사용. "
            "성능 보고서에서 OpenAI/Gemini 를 같은 질문으로 번갈아 호출할 때 씁니다."
        ),
    )
    use_rag: bool = Field(
        True,
        description=(
            "[내부용] WEB 에서는 보내지 마세요. false 면 문서 검색 없이 답변합니다. "
            "RAG 가 답변 품질에 실제로 얼마나 기여하는지 측정할 때 씁니다."
        ),
    )


class ChatResponse(BaseModel):
    """WEB 이 실제로 쓰는 값만 담는다.

    지연·토큰·모델명 같은 계측값은 응답에 넣지 않는다. DB 컬럼도 없고 화면에
    쓸 일도 없어서, 서버 로그 파일(`METRICS_PATH`)에만 남긴다.
    """

    answer: str = Field(..., description="chat.message 에 그대로 저장 (speaker='llm')")
    topic: str = Field(
        ...,
        description=(
            "chat.topic 에 그대로 저장 (사용자 발화 행). "
            f"항상 다음 중 하나: {', '.join(TOPIC_CATEGORIES)}"
        ),
    )
    sources: list[Source] = Field(
        default_factory=list,
        description=(
            "근거 문서. 답변 하단에 문서명을 노출하는 데 쓴다(스토리보드 13p). "
            "RAG 실패 시에도 500 대신 빈 배열로 응답한다."
        ),
    )
    rag_degraded: bool = Field(
        False,
        description="true면 RAG 검색에 실패해 문서 없이 생성된 답변. 저장 불필요, UI 안내용",
    )


class TopicRequest(BaseModel):
    message: str = Field(..., min_length=1)
    source_files: list[str] = Field(
        default_factory=list,
        description="선택. RAG가 찾은 문서명을 넣으면 분류 힌트로 쓴다.",
    )
    provider: ProviderName | None = Field(None, description="[내부용] 미지정 시 서버 기본값")


class TopicResponse(BaseModel):
    topic: str = Field(..., description=f"항상 다음 중 하나: {', '.join(TOPIC_CATEGORIES)}")
    cached: bool = Field(False, description="동일 질문 캐시 적중 여부")


class ChatroomNameRequest(BaseModel):
    message: str = Field(..., min_length=1, description="해당 채팅방의 첫 질문")
    provider: ProviderName | None = Field(None, description="[내부용] 미지정 시 서버 기본값")


class ChatroomNameResponse(BaseModel):
    name: str = Field(..., description="chatroom.chatroom_name 에 그대로 저장 (100자 이내)")


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    providers: dict[str, bool] = Field(..., description="프로바이더별 API 키 설정 여부")
    default_provider: ProviderName
    rag: Literal["up", "down", "mock"]
    topic_categories: list[str] = Field(
        ..., description="현재 서버가 쓰는 카테고리 목록. 대시보드가 이걸 읽어 차트 축을 맞출 수 있다."
    )


class ErrorResponse(BaseModel):
    """에러는 항상 이 형태. `message` 는 프론트가 그대로 출력 가능한 한국어."""

    error_code: Literal[
        "LLM_TIMEOUT",
        "LLM_RATE_LIMITED",
        "LLM_UNAVAILABLE",
        "PROVIDER_NOT_CONFIGURED",
        "INVALID_REQUEST",
        "INTERNAL_ERROR",
    ] = Field(..., description="프로그램이 분기할 때 쓰는 고정 문자열")
    message: str = Field(
        ..., description="프론트에 그대로 출력해도 되는 한국어. 에러마다 문구가 다르다"
    )


# 라우트에 붙여 Swagger 가 에러 형태까지 보여주게 한다.
# 이게 없으면 /docs 에 성공 응답만 나와서, WEB 담당자가 에러 형태를 문서에서만
# 확인할 수 있다.
ERROR_RESPONSES: dict = {
    422: {"model": ErrorResponse, "description": "요청 형식 오류 — INVALID_REQUEST"},
    429: {
        "model": ErrorResponse,
        "description": "벤더 API 호출 한도 초과 — LLM_RATE_LIMITED. Retry-After 헤더 참고",
    },
    500: {"model": ErrorResponse, "description": "예상 밖 오류 — INTERNAL_ERROR"},
    503: {
        "model": ErrorResponse,
        "description": "프로바이더 장애 또는 키 미설정 — LLM_UNAVAILABLE / PROVIDER_NOT_CONFIGURED",
    },
    504: {"model": ErrorResponse, "description": "생성 타임아웃 — LLM_TIMEOUT"},
}
