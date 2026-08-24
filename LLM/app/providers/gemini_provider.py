"""Gemini 프로바이더 (google-genai SDK).

OpenAI 쪽과 두 가지가 다르다.
1. system 프롬프트가 messages 배열이 아니라 `system_instruction` 설정으로 들어간다.
2. assistant 역할 이름이 "model" 이다.

topic 분류는 `response_schema` 의 enum 으로 디코딩을 제약한다 (OpenAI strict 와 같은 목적).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

from app.config import get_settings
from app.errors import ProviderNotConfigured, ProviderUnavailable
from app.providers.base import GenerationResult, LLMProvider, Message


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise ProviderNotConfigured()
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable("google-genai SDK가 설치되지 않았습니다.") from exc

        self._types = types
        self.model = settings.gemini_model
        self._client = genai.Client(api_key=settings.gemini_api_key)

    @staticmethod
    def _contents(messages: Sequence[Message]) -> list[dict]:
        # Gemini 는 assistant 를 "model" 이라고 부른다.
        return [
            {
                "role": "model" if m.role == "assistant" else "user",
                "parts": [{"text": m.content}],
            }
            for m in messages
        ]

    def _config(self, system: str, temperature: float, max_tokens: int | None):
        return self._types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

    @staticmethod
    def _usage(resp) -> tuple[int | None, int | None]:
        meta = getattr(resp, "usage_metadata", None)
        if meta is None:
            return None, None
        return (
            getattr(meta, "prompt_token_count", None),
            getattr(meta, "candidates_token_count", None),
        )

    async def preconnect(self) -> None:
        # 모델 목록 조회는 토큰도, generate_content 쿼터도 쓰지 않으면서
        # 같은 호스트(generativelanguage.googleapis.com)로 붙는다.
        await self._client.aio.models.list()

    async def generate(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> GenerationResult:
        resp = await self._client.aio.models.generate_content(
            model=self.model,
            contents=self._contents(messages),
            config=self._config(system, temperature, max_tokens),
        )
        prompt_tokens, completion_tokens = self._usage(resp)
        return GenerationResult(
            text=resp.text or "",
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def stream(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        chunks = await self._client.aio.models.generate_content_stream(
            model=self.model,
            contents=self._contents(messages),
            config=self._config(system, temperature, max_tokens),
        )
        async for chunk in chunks:
            text = getattr(chunk, "text", None)
            if text:
                yield text

    async def classify(
        self,
        *,
        system: str,
        user_content: str,
        allowed: Sequence[str],
    ) -> str:
        config = self._types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            response_mime_type="application/json",
            response_schema={
                "type": "OBJECT",
                "properties": {"topic": {"type": "STRING", "enum": list(allowed)}},
                "required": ["topic"],
            },
        )
        resp = await self._client.aio.models.generate_content(
            model=self.model,
            contents=[{"role": "user", "parts": [{"text": user_content}]}],
            config=config,
        )
        return str(json.loads(resp.text or "{}").get("topic", ""))
