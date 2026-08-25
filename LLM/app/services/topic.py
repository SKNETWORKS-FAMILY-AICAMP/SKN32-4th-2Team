"""주제(topic) 분류.

`chat.topic` 은 대시보드 도넛 차트의 GROUP BY 축이므로, 같은 의도의 질문이
매번 다른 문자열로 저장되면 차트가 조각난다. 그래서 '생성'이 아니라 '분류'로 다룬다.

안정성 3중 장치:
1. 디코딩 제약 — 프로바이더가 enum 밖 토큰을 생성하지 못하게 한다 (근본 대책)
2. 화이트리스트 검증 — 그래도 이상한 값이 오면 '기타'로 떨어뜨린다
3. 해시 캐시 — 같은 질문은 항상 같은 결과. 시연 재현성 + 호출비 절감

`seed` 는 쓰지 않는다. OpenAI/Gemini 모두 best-effort 라 보장되지 않고,
무엇보다 입력 문장이 조금만 달라지면 무용지물이라 위 1~2번이 본질적인 해법이다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from collections import OrderedDict
from collections.abc import Sequence

from app.config import get_settings
from app.domain import FALLBACK_TOPIC, TOPIC_CATEGORIES
from app.errors import LLMServiceError
from app.prompts import TOPIC_SYSTEM, build_topic_input
from app.providers.registry import get_provider

logger = logging.getLogger(__name__)

_CACHE_MAX = 2048
_cache: OrderedDict[tuple[str, str], str] = OrderedDict()

_NON_MEANINGFUL = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize(message: str) -> str:
    """캐시 키용 정규화.

    유니코드 정규화(NFKC) + 공백/문장부호 제거 + 소문자화.
    "연차 며칠?" 과 "연차 며칠" 과 "연차며칠!!" 이 같은 키가 된다.
    """
    text = unicodedata.normalize("NFKC", message).lower()
    return _NON_MEANINGFUL.sub("", text)


def _cache_get(key: tuple[str, str]) -> str | None:
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    return None


def _cache_put(key: tuple[str, str], value: str) -> None:
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


def clear_cache() -> None:
    _cache.clear()


def validate(raw: str) -> str:
    """화이트리스트 검증. 목록 밖이면 '기타'."""
    candidate = (raw or "").strip()
    if candidate in TOPIC_CATEGORIES:
        return candidate
    logger.warning("카테고리 목록을 벗어난 분류 결과 — '%s' → '%s'", candidate, FALLBACK_TOPIC)
    return FALLBACK_TOPIC


async def classify(
    message: str,
    source_files: Sequence[str] = (),
    provider_name: str | None = None,
    use_cache: bool = True,
) -> tuple[str, bool]:
    """질문을 고정 카테고리 하나로 분류한다.

    Returns:
        (topic, cached)
    """
    provider = get_provider(provider_name)
    key = (provider.name, normalize(message))

    if use_cache:
        hit = _cache_get(key)
        if hit is not None:
            return hit, True

    try:
        raw = await asyncio.wait_for(
            provider.classify(
                system=TOPIC_SYSTEM,
                user_content=build_topic_input(message, source_files),
                allowed=TOPIC_CATEGORIES,
            ),
            timeout=get_settings().llm_timeout_sec,
        )
        topic = validate(raw)
    except LLMServiceError:
        raise
    except Exception as exc:
        # 주제 분류 실패로 답변 전체를 실패시키지 않는다.
        logger.warning("주제 분류 실패 — '%s' 로 대체합니다: %s", FALLBACK_TOPIC, exc)
        topic = FALLBACK_TOPIC

    if use_cache:
        _cache_put(key, topic)
    return topic, False
