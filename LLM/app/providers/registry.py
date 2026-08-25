"""이름 → 프로바이더 인스턴스.

인스턴스는 캐시한다. HTTP 커넥션 풀을 요청마다 새로 만들면 지연이 늘어나
성능 보고서 수치가 왜곡된다.

생성 비용이 작지 않다 — SDK 모듈 import 와 HTTP 클라이언트 구성까지 포함해
실측으로 OpenAI 약 1.5초, Gemini 약 2.4초다. 그대로 두면 **서버 기동 후
첫 사용자**가 그 시간을 대신 물게 되므로, `warm_up()` 을 lifespan 에서 불러
기동 시점에 미리 낸다.
"""

from __future__ import annotations

import logging
import time

from app.config import get_settings
from app.errors import LLMServiceError, ProviderNotConfigured
from app.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_cache: dict[str, LLMProvider] = {}

# 운영 API에서 지원하는 프로바이더. Qwen은 qwen-sft/의 별도 연구 트랙에만 둔다.
SUPPORTED = ("openai", "gemini")

# app.config.Settings.is_configured()가 참조하는 호환용 상수다.
# 운영 SUPPORTED에 키 없는 프로바이더는 없다.
KEYLESS: tuple[str, ...] = ()


def get_provider(name: str | None = None) -> LLMProvider:
    settings = get_settings()
    resolved = name or settings.default_provider

    if resolved not in SUPPORTED:
        raise ProviderNotConfigured(f"지원하지 않는 프로바이더입니다: {resolved}")

    if resolved in _cache:
        return _cache[resolved]

    if settings.llm_mode == "mock":
        from app.providers.mock_provider import MockProvider

        provider: LLMProvider = MockProvider(alias=resolved)
    elif resolved == "openai":
        from app.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider()
    else:
        from app.providers.gemini_provider import GeminiProvider

        provider = GeminiProvider()

    _cache[resolved] = provider
    return provider


def warm_up() -> dict[str, bool]:
    """설정된 프로바이더를 미리 만들어 둔다. 서버 기동 시 한 번 부른다.

    하나만 설정된 환경에서도 서버는 떠야 하므로 준비 실패가 기동을 막지 않게
    예외를 흡수한다.

    Returns:
        {프로바이더명: 준비 성공 여부}
    """
    result: dict[str, bool] = {}
    for name in SUPPORTED:
        started = time.perf_counter()
        try:
            get_provider(name)
            result[name] = True
            logger.info("프로바이더 준비 %s (%.0fms)", name, (time.perf_counter() - started) * 1000)
        except LLMServiceError as exc:
            result[name] = False
            logger.warning("프로바이더 준비 건너뜀 %s — %s", name, exc.message)
        except Exception:
            result[name] = False
            logger.exception("프로바이더 준비 실패 %s", name)
    return result


async def preconnect_all(pool: int = 2) -> None:
    """준비된 프로바이더의 벤더 API 연결을 미리 열어둔다.

    `/v1/chat` 은 답변 생성과 주제 분류를 병렬로 돌리므로 첫 요청에 커넥션을
    **동시에 2개** 연다. 하나만 데워두면 나머지 하나가 여전히 핸드셰이크 비용을
    문다. 그래서 `pool` 개만큼 동시에 열어 풀에 남긴다.

    실패해도 기동을 막지 않는다. 연결이 안 되면 첫 요청이 조금 느릴 뿐이다.
    """
    import asyncio

    for name, provider in list(_cache.items()):
        started = time.perf_counter()
        results = await asyncio.gather(
            *(provider.preconnect() for _ in range(pool)), return_exceptions=True
        )
        failed = [r for r in results if isinstance(r, BaseException)]
        if failed:
            logger.warning("연결 예열 실패 %s — 첫 요청이 느릴 수 있습니다: %s", name, failed[0])
        else:
            logger.info(
                "연결 예열 %s ×%d (%.0fms)", name, pool, (time.perf_counter() - started) * 1000
            )


def is_available(name: str) -> bool:
    """`/health` 표시용. 이 프로바이더로 요청을 보낼 수 있는가.

    API 키 설정 여부로 판단한다. 예열 실패만으로 down으로 표시하면 일시적인
    네트워크 문제에 과민하게 반응할 수 있다.
    """
    settings = get_settings()
    return settings.is_configured(name)


def reset_cache() -> None:
    """테스트/설정 변경용."""
    _cache.clear()
