"""Ollama를 통한 로컬 Qwen 프로바이더.

Ollama의 REST API만 사용하므로 별도의 ``ollama`` Python 패키지가 필요하지 않다.
특히 주제 분류는 ``format``에 JSON Schema를 전달한다. 이것은 JSON 형식으로
답해 달라는 프롬프트 지시가 아니라 Ollama의 문법 제약 디코딩이므로, ``topic``에
허용 목록 밖 문자열이 생성되는 것을 막는다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.config import get_settings
from app.providers.base import GenerationResult, LLMProvider, Message


class QwenProvider(LLMProvider):
    """Qwen2.5를 Ollama의 ``/api/chat`` API로 호출한다."""

    name = "qwen"

    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.qwen_model
        self._keep_alive = settings.qwen_keep_alive
        self._client = httpx.AsyncClient(
            base_url=settings.qwen_base_url.rstrip("/") + "/",
            timeout=settings.llm_timeout_sec,
        )

    @staticmethod
    def _messages(system: str, messages: Sequence[Message]) -> list[dict[str, str]]:
        return [{"role": "system", "content": system}] + [
            {"role": message.role, "content": message.content} for message in messages
        ]

    def _payload(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        temperature: float,
        max_tokens: int | None,
        stream: bool,
        format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            # Ollama의 출력 길이 옵션 이름은 OpenAI의 max_tokens와 다르다.
            options["num_predict"] = max_tokens

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(system, messages),
            "stream": stream,
            "options": options,
            # 매 호출마다 상주 시간을 갱신한다. 이걸 안 보내면 Ollama 기본값(5분)이
            # 적용돼 잠깐 쉬는 사이 모델이 내려가고, 다음 호출이 로딩 4초를 문다.
            "keep_alive": self._keep_alive,
        }
        if format is not None:
            payload["format"] = format
        return payload

    @staticmethod
    def _usage(payload: dict[str, Any]) -> tuple[int | None, int | None]:
        return payload.get("prompt_eval_count"), payload.get("eval_count")

    async def preconnect(self) -> None:
        """모델이 있는지 확인하고, **VRAM 에 미리 올려둔다.**

        존재 확인만으로는 부족하다. Ollama 는 실제 호출이 올 때 비로소 모델을
        메모리에 올리는데 실측 4초가 걸린다(콜드 5.8초 vs 웜 1.4초).
        그대로 두면 서버 기동 후 첫 사용자가 그 시간을 대신 문다.

        빈 messages 로 요청하면 Ollama 는 **토큰을 생성하지 않고 로딩만** 한다.
        """
        response = await self._client.get("api/tags")
        response.raise_for_status()
        models = response.json().get("models", [])
        available = {item.get("name") for item in models if isinstance(item, dict)}
        if self.model not in available:
            raise RuntimeError(
                f"Ollama에 모델 '{self.model}'이 없습니다. "
                f"'ollama pull {self.model}'을 먼저 실행하세요."
            )

        load = await self._client.post(
            "api/chat",
            json={"model": self.model, "messages": [], "keep_alive": self._keep_alive},
            timeout=180.0,  # 콜드 로딩은 일반 요청 타임아웃보다 오래 걸린다
        )
        load.raise_for_status()

    async def generate(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> GenerationResult:
        response = await self._client.post(
            "api/chat",
            json=self._payload(
                system=system,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            ),
        )
        response.raise_for_status()
        payload = response.json()
        prompt_tokens, completion_tokens = self._usage(payload)
        message = payload.get("message") or {}
        return GenerationResult(
            text=str(message.get("content") or ""),
            model=str(payload.get("model") or self.model),
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
        """Ollama의 newline-delimited JSON 응답에서 토큰 조각만 전달한다."""
        async with self._client.stream(
            "POST",
            "api/chat",
            json=self._payload(
                system=system,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            ),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                payload = json.loads(line)
                message = payload.get("message") or {}
                content = message.get("content")
                if content:
                    yield str(content)

    async def classify(
        self,
        *,
        system: str,
        user_content: str,
        allowed: Sequence[str],
    ) -> str:
        """문법 제약된 JSON Schema로 허용 카테고리 하나만 생성한다.

        ``format``은 Ollama의 structured outputs 기능이다. enum이 디코더에
        전달되므로 프롬프트 준수 여부에 의존하지 않는다.
        """
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {"topic": {"type": "string", "enum": list(allowed)}},
            "required": ["topic"],
            "additionalProperties": False,
        }
        response = await self._client.post(
            "api/chat",
            json=self._payload(
                system=system,
                messages=[Message(role="user", content=user_content)],
                temperature=0,
                max_tokens=None,
                stream=False,
                format=schema,
            ),
        )
        response.raise_for_status()
        payload = response.json()
        content = str((payload.get("message") or {}).get("content") or "{}")
        parsed = json.loads(content)
        return str(parsed.get("topic") or "")
