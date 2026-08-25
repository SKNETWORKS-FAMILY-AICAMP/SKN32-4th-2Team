"""채팅방 이름 생성.

`chatroom.chatroom_name` 은 VARCHAR(100) 이고 기본값이 '새 대화' 다.
사용자의 첫 질문으로 읽기 좋은 제목을 만들어 사이드바를 알아보기 쉽게 한다.
"""

from __future__ import annotations

import asyncio
import logging
import re

from app.config import get_settings
from app.domain import CHATROOM_NAME_MAX_LEN, CHATROOM_NAME_TARGET_LEN
from app.prompts import CHATROOM_NAME_SYSTEM
from app.providers.base import Message
from app.providers.registry import get_provider

logger = logging.getLogger(__name__)

DEFAULT_NAME = "새 대화"  # schema 의 chatroom_name DEFAULT 와 동일

_STRIP_CHARS = re.compile(r'^["\'\s]+|["\'\s.]+$')


def sanitize(raw: str) -> str:
    """따옴표/개행 제거 후 DB 컬럼 한계에 맞춰 자른다."""
    name = _STRIP_CHARS.sub("", (raw or "").replace("\n", " ")).strip()
    if not name:
        return DEFAULT_NAME
    # 모델이 길게 뱉는 경우가 있어 표시 목표 길이로 먼저 자른다.
    if len(name) > CHATROOM_NAME_TARGET_LEN:
        name = name[:CHATROOM_NAME_TARGET_LEN].rstrip()
    return name[:CHATROOM_NAME_MAX_LEN]


def fallback_name(message: str) -> str:
    """LLM 호출이 실패해도 채팅방 이름은 있어야 한다 — 질문 앞부분을 쓴다."""
    trimmed = " ".join(message.split())[:CHATROOM_NAME_TARGET_LEN].strip()
    return trimmed or DEFAULT_NAME


async def generate_name(message: str, provider_name: str | None = None) -> str:
    provider = get_provider(provider_name)
    try:
        result = await asyncio.wait_for(
            provider.generate(
                system=CHATROOM_NAME_SYSTEM,
                messages=[Message(role="user", content=message)],
                temperature=0.3,
                max_tokens=60,
            ),
            timeout=get_settings().llm_timeout_sec,
        )
        name = sanitize(result.text)
        # mock 모드나 이상 응답이 그대로 제목이 되는 것을 막는다.
        return name if name != DEFAULT_NAME else fallback_name(message)
    except Exception as exc:
        logger.warning("채팅방 이름 생성 실패 — 질문 앞부분으로 대체합니다: %s", exc)
        return fallback_name(message)
