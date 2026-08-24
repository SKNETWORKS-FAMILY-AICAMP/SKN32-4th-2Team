"""OpenAI 프로바이더.

topic 분류는 Structured Outputs(`strict: true` + `enum`)로 디코딩 자체를 제약한다.
프롬프트로 "이 중에서 골라줘"라고 부탁하는 것과 달리, 목록 밖 값이 생성 불가능해진다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

from app.config import get_settings
from app.errors import ProviderNotConfigured, ProviderUnavailable
from app.providers.base import GenerationResult, LLMProvider, Message


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise ProviderNotConfigured()
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable("OpenAI SDK가 설치되지 않았습니다.") from exc

        self.model = settings.openai_model
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_sec,
            max_retries=0,  # 타임아웃 예산을 재시도로 갉아먹지 않게
        )

    @staticmethod
    def _payload(system: str, messages: Sequence[Message]) -> list[dict[str, str]]:
        return [{"role": "system", "content": system}] + [
            {"role": m.role, "content": m.content} for m in messages
        ]

    async def preconnect(self) -> None:
        # 모델 목록 조회는 토큰을 쓰지 않으면서 같은 호스트로 붙으므로,
        # 커넥션 풀에 TLS 연결이 남는다. 그 뒤 chat.completions 가 재사용한다.
        await self._client.models.list()

    async def generate(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> GenerationResult:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=self._payload(system, messages),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        usage = resp.usage
        return GenerationResult(
            text=resp.choices[0].message.content or "",
            model=self.model,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )

    async def stream(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        chunks = await self._client.chat.completions.create(
            model=self.model,
            messages=self._payload(system, messages),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in chunks:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def classify(
        self,
        *,
        system: str,
        user_content: str,
        allowed: Sequence[str],
    ) -> str:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "topic_classification",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"topic": {"type": "string", "enum": list(allowed)}},
                        "required": ["topic"],
                        "additionalProperties": False,
                    },
                },
            },
        )
        raw = resp.choices[0].message.content or "{}"
        return str(json.loads(raw).get("topic", ""))
