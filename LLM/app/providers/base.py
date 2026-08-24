"""프로바이더 공통 인터페이스.

services/ 계층은 이 인터페이스만 보고, 어떤 벤더인지 모른다.
그래야 성능 보고서에서 프로바이더만 갈아끼워 비교할 수 있다.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal

Role = Literal["user", "assistant"]


@dataclass(slots=True)
class Message:
    role: Role
    content: str


@dataclass(slots=True)
class GenerationResult:
    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider(abc.ABC):
    """모든 프로바이더가 구현해야 하는 3가지 동작."""

    name: str
    model: str

    @abc.abstractmethod
    async def generate(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> GenerationResult:
        """한 번에 전체 응답을 생성한다."""

    @abc.abstractmethod
    def stream(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """토큰 조각을 순서대로 흘려보낸다."""

    async def preconnect(self) -> None:
        """벤더 API 로의 TCP/TLS 연결을 미리 열어둔다.

        객체를 만들어두는 것만으로는 부족하다. 실제 연결은 첫 API 호출 때 맺어지고
        핸드셰이크에만 실측 700ms 가 든다. 서버 기동 시 미리 열어 첫 사용자가
        그 비용을 물지 않게 한다.

        **토큰을 쓰지 않는 호출**로 구현해야 한다(모델 목록 조회 등).
        실패해도 서비스에 영향이 없어야 하므로 호출부에서 예외를 흡수한다.
        기본 구현은 아무것도 하지 않는다 — mock 프로바이더처럼 연결이 없는 경우.
        """

    @abc.abstractmethod
    async def classify(
        self,
        *,
        system: str,
        user_content: str,
        allowed: Sequence[str],
    ) -> str:
        """`allowed` 안의 값 **하나**만 반환한다.

        구현체는 반드시 디코딩 단계에서 제약을 걸어야 한다
        (OpenAI Structured Outputs `strict`, Gemini `response_schema` 의 enum).
        프롬프트로만 부탁하는 방식은 목록 이탈을 막지 못하므로 금지.
        """
