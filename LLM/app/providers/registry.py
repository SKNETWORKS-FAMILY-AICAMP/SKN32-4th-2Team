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

SUPPORTED = ("openai", "gemini", "qwen")

# 키가 필요 없는 프로바이더. is_configured() 가 키 유무로 판단하므로 예외를 둔다.
KEYLESS = ("qwen",)

# 기동 시 예열에서 실제로 연결된 프로바이더. `/health` 가 참고한다.
#
# 키가 없는 프로바이더(Qwen)는 "키가 있는가" 로 가용 여부를 알 수 없다. 그래서
# 예전에는 /health 가 Ollama 가 안 떠 있어도 `qwen: true` 라고 답했다. 팀원이
# 다른 PC 에서 받아 실행하면 Ollama 는 대개 없으므로, 그 화면만 보고 쓸 수 있는
# 줄 알게 된다.
#
# 객체 생성(warm_up)만으로는 알 수 없다는 점이 핵심이다. QwenProvider 는 httpx
# 클라이언트만 만들 뿐 네트워크를 타지 않아 Ollama 가 죽어 있어도 성공한다.
# 실제 접속은 preconnect 에서만 드러난다.
_reachable: dict[str, bool] = {}


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
    elif resolved == "qwen":
        # 로컬 오픈소스(Ollama). 아직 구현 전이면 서버가 죽지 않고 503 으로 떨어지게 한다.
        try:
            from app.providers.qwen_provider import QwenProvider
        except ImportError as exc:
            raise ProviderNotConfigured(
                "Qwen 프로바이더가 아직 준비되지 않았습니다."
            ) from exc
        provider = QwenProvider()
    else:
        from app.providers.gemini_provider import GeminiProvider

        provider = GeminiProvider()

    _cache[resolved] = provider
    return provider


def warm_up() -> dict[str, bool]:
    """설정된 프로바이더를 미리 만들어 둔다. 서버 기동 시 한 번 부른다.

    키가 없는 프로바이더는 건너뛴다 — 하나만 설정된 환경에서도 서버는 떠야 하고,
    나중에 그 프로바이더로 요청이 오면 그때 정상적으로 503 을 돌려주면 된다.
    준비 실패가 기동을 막지 않도록 예외를 흡수한다.

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
        _reachable[name] = not failed
        if failed:
            logger.warning("연결 예열 실패 %s — 첫 요청이 느릴 수 있습니다: %s", name, failed[0])
        else:
            logger.info(
                "연결 예열 %s ×%d (%.0fms)", name, pool, (time.perf_counter() - started) * 1000
            )


def is_available(name: str) -> bool:
    """`/health` 표시용. 이 프로바이더로 요청을 보낼 수 있는가.

    키를 쓰는 프로바이더는 **키 유무**로 본다. 예열이 잠깐 실패했다고 down 으로
    표시하면 일시적 네트워크 문제에 과민하게 반응한다.

    키가 없는 프로바이더는 키로 판단할 수 없으므로 **예열 성공 여부**로 본다.
    예열을 아직 안 돌렸으면(테스트 등) 설정값을 그대로 따른다.
    """
    settings = get_settings()
    if name in KEYLESS and settings.llm_mode != "mock":
        return _reachable.get(name, settings.is_configured(name))
    return settings.is_configured(name)


def reset_cache() -> None:
    """테스트/설정 변경용."""
    _cache.clear()
    _reachable.clear()
