"""벤치마크용 호출 속도 제어와 재시도.

**서비스 본체가 아니라 벤치마크 전용이다.** 실사용 요청은 429 를 받으면 바로
돌려준다 — 벤더가 알려주는 대기 시간이 보통 30초 이상이라 요청 타임아웃(15초)
안에 처리할 수 없고, 사용자를 30초 붙잡아두는 것보다 "잠시 후 다시" 가 낫다.

반면 벤치마크는 34문항 × 프로바이더 수만큼 돌려야 하므로 중간에 끊기면 안 된다.
여기서는 느긋하게 기다린다.

Gemini 무료 티어는 **분당 20회** 다(실측 확인). 그냥 돌리면 금방 429 가 난다.

주의: `/v1/chat` 한 번은 프로바이더를 **2회** 호출한다(답변 생성 + 주제 분류).
따라서 분당 20회 한도에서 실제로 보낼 수 있는 `/v1/chat` 은 **분당 10회**다.
`RateLimiter(rpm=...)` 에는 프로바이더 호출 기준이 아니라 **요청 기준** 값을
넣어야 한다. Gemini 로 벤치를 돌린다면 `rpm=10` 이 상한이다.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """분당 호출 수를 제한한다 (슬라이딩 윈도우).

    토큰 버킷 대신 '최근 60초 안의 호출 시각'을 들고 있다가 한도에 닿으면
    가장 오래된 호출이 윈도우 밖으로 나갈 때까지 기다린다. 구현이 단순하고
    분당 한도라는 실제 제약과 정확히 맞는다.

    `safety` 는 한도를 그대로 쓰지 않고 약간 여유를 두기 위한 값이다.
    벤더의 카운트 시점과 우리 시점이 정확히 같지 않아, 20/20 을 채우면
    경계에서 종종 429 가 난다.
    """

    rpm: int
    window_sec: float = 60.0
    safety: int = 2
    _calls: list[float] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def limit(self) -> int:
        return max(1, self.rpm - self.safety)

    async def acquire(self) -> float:
        """호출 직전에 부른다. 기다린 시간(초)을 돌려준다."""
        async with self._lock:
            waited = 0.0
            while True:
                now = time.monotonic()
                self._calls = [t for t in self._calls if now - t < self.window_sec]
                if len(self._calls) < self.limit:
                    self._calls.append(now)
                    return waited
                sleep_for = self.window_sec - (now - self._calls[0]) + 0.1
                await asyncio.sleep(sleep_for)
                waited += sleep_for


class RateLimited(Exception):
    """호출 대상이 429 를 돌려줬다. `retry_after` 는 벤더가 권한 대기 시간(초)."""

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(f"rate limited (retry_after={retry_after})")


async def with_retry(
    call,
    *,
    attempts: int = 5,
    base_delay: float = 5.0,
    max_delay: float = 90.0,
    on_wait=None,
):
    """`call()` 을 부르고 429 면 기다렸다 다시 시도한다.

    대기 시간은 이 순서로 정한다.
    1. 벤더가 알려준 `retry_after` (가장 정확하다)
    2. 없으면 지수 백오프 + 지터

    지터를 넣는 이유: 여러 요청이 동시에 429 를 맞으면 같은 시각에 몰려서
    재시도하게 되고, 그럼 또 429 가 난다.

    429 가 아닌 예외는 그대로 올려보낸다. 벤치마크에서 진짜 실패를 재시도로
    가려버리면 에러율 측정이 무의미해진다.
    """
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except RateLimited as exc:
            if attempt == attempts:
                raise
            delay = exc.retry_after if exc.retry_after else base_delay * (2 ** (attempt - 1))
            delay = min(delay, max_delay) + random.uniform(0, 1.5)
            if on_wait:
                on_wait(attempt, delay)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")
