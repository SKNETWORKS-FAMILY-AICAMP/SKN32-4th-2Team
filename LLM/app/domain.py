"""도메인 상수와 내부 모델.

`TOPIC_CATEGORIES` 는 대시보드 도넛 차트(`chat.topic` GROUP BY)의 축이 되므로
**팀 합의 대상**이다. 여기 한 곳만 고치면 분류기 프롬프트, enum 제약 스키마,
검증 로직이 모두 따라온다.

카테고리는 임의로 정한 것이 아니라 RAG 브랜치(`RAG/res/pdf/`)에 실제로 들어 있는
규정·법령 PDF 28건을 묶어 도출했다. 매핑 근거는 docs/API.md 참조.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from app.schemas import Source

# chat.topic 은 VARCHAR(100) 이므로 모든 값이 100자 미만이어야 한다.
TOPIC_CATEGORIES: Final[tuple[str, ...]] = (
    "휴가/휴직",
    "근태/근무형태",
    "급여/보수",
    "채용/임용",
    "인사/승진",
    "복리후생",
    # 원래 이름은 `복무/징계` 였다. 뜻은 '비위·징계' 인데, 한국어에서 "복무" 는
    # 그냥 '근무한다' 는 뜻으로도 쓰여서 휴가·근태 질문까지 끌어왔다. 프롬프트에
    # 경계 설명을 붙여 덮었었지만, 이름을 바로잡는 쪽이 근본 해결이다.
    # 측정 근거는 prompts.py 의 `_CATEGORY_GUIDE` 위 주석 참조.
    "징계/행동강령",
    "기타",
)

# 분류가 불가능하거나 검증에 실패했을 때 떨어질 곳.
FALLBACK_TOPIC: Final[str] = "기타"

# DB 컬럼 제약 (sql/rag_chatbot_schema.sql)
TOPIC_MAX_LEN: Final[int] = 100  # chat.topic VARCHAR(100)
CHATROOM_NAME_MAX_LEN: Final[int] = 100  # chatroom.chatroom_name VARCHAR(100)

# 채팅방 이름은 사이드바에 들어가므로 컬럼 한계보다 훨씬 짧게 유지한다.
CHATROOM_NAME_TARGET_LEN: Final[int] = 20

assert FALLBACK_TOPIC in TOPIC_CATEGORIES
assert all(len(c) <= TOPIC_MAX_LEN for c in TOPIC_CATEGORIES)


@dataclass(slots=True)
class RetrievedChunk:
    """RAG 가 돌려준 문서 조각. **내부 전용이며 API 응답에 나가지 않는다.**

    `content` 는 프롬프트의 [참고 문서] 블록을 만드는 데 쓰고, `score` 는 검색 품질
    계측에 쓴다. 둘 다 화면에 표시할 값이 아니라 응답에서는 뺀다 — 특히 `content` 는
    청크당 수백 자라, 그대로 실어 보내면 응답 대부분이 버려지는 데이터가 된다.

    WEB 에 나가는 것은 `to_source()` 로 추린 문서명·페이지·doc_id 뿐이다.
    """

    original_file_name: str
    content: str
    doc_id: int | None = None
    page: int | None = None
    score: float | None = None

    def to_source(self) -> "Source":
        from app.schemas import Source

        return Source(
            doc_id=self.doc_id,
            original_file_name=self.original_file_name,
            page=self.page,
        )
