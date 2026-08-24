"""요청별 계측 로그.

지연·토큰·모델명은 API 응답에 넣지 않는다. DB 컬럼도 없고 화면에 쓸 일도 없어서,
여기서 **로그 파일에만** 남긴다. 두 갈래로 기록한다.

1. JSONL 파일 (`METRICS_PATH`) — 성능 보고서(bench/report.py)가 읽어 집계한다
2. 콘솔 로그 한 줄 — 서버 띄워놓고 눈으로 확인할 때

기록 실패가 서비스에 영향을 주면 안 되므로 모든 예외를 삼킨다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from app.config import get_settings

logger = logging.getLogger("llm.metrics")


@dataclass(slots=True)
class CallMetrics:
    """한 번의 요청에서 측정한 값. API 응답에는 실리지 않는다."""

    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    ttft_ms: int | None = None
    rag_ms: int | None = None

    def summary(self) -> str:
        parts = [f"{self.provider}/{self.model}", f"{self.latency_ms}ms"]
        if self.ttft_ms is not None:
            parts.append(f"ttft={self.ttft_ms}ms")
        if self.rag_ms is not None:
            parts.append(f"rag={self.rag_ms}ms")
        if self.prompt_tokens is not None or self.completion_tokens is not None:
            parts.append(f"tok={self.prompt_tokens}/{self.completion_tokens}")
        return " ".join(parts)


def record(event: str, **fields: Any) -> None:
    """JSONL 한 줄 추가."""
    settings = get_settings()
    if not settings.metrics_enabled:
        return
    try:
        path = settings.metrics_file
        path.parent.mkdir(parents=True, exist_ok=True)
        # 로컬 시각 + UTC 오프셋(예: 2026-07-31T15:08:16.490+09:00).
        # UTC 로만 남기면 콘솔 로그(로컬 시각)나 DB 의 created_at(MySQL CURRENT_TIMESTAMP,
        # 서버 로컬)과 대조할 때 매번 시차를 계산해야 한다. 오프셋을 붙여
        # 읽기 쉬우면서도 해석이 모호하지 않게 한다.
        row = {"ts": datetime.now().astimezone().isoformat(), "event": event, **fields}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover - 계측 실패는 무시
        logger.debug("계측 기록 실패: %s", exc)


def record_chat(
    event: str,
    *,
    chatroom_id: str,
    topic: str,
    rag_degraded: bool,
    source_count: int,
    source_files: Sequence[str] = (),
    metrics: CallMetrics,
) -> None:
    """한 번의 대화 처리 결과를 콘솔 한 줄 + JSONL 한 줄로 남긴다.

    `source_files` 는 화면에 나가지 않지만 여기 기록한다. 성능 보고서에서
    '정답 근거 문서가 검색 결과에 포함됐는가'(recall@k)를 사후 집계하려면
    어떤 문서가 걸렸는지가 남아 있어야 한다.
    """
    logger.info(
        "%s room=%s topic=%s docs=%d%s | %s",
        event,
        chatroom_id,
        topic,
        source_count,
        " (RAG 실패)" if rag_degraded else "",
        metrics.summary(),
    )
    record(
        event,
        chatroom_id=chatroom_id,
        topic=topic,
        rag_degraded=rag_degraded,
        source_count=source_count,
        source_files=list(source_files),
        **asdict(metrics),
    )


def record_error(
    event: str,
    *,
    chatroom_id: str,
    error_code: str,
    provider: str,
    model: str,
    latency_ms: int,
    rag_ms: int | None = None,
) -> None:
    """실패한 요청을 기록한다.

    성공과 마찬가지로 콘솔에도 한 줄 남긴다. JSONL 에만 남기면 시연 중 실패했을 때
    터미널에는 아무것도 안 보여서 바로 알아차릴 수 없다.
    """
    logger.warning(
        "%s room=%s %s | %s/%s %dms", event, chatroom_id, error_code, provider, model, latency_ms
    )
    record(
        event,
        chatroom_id=chatroom_id,
        error_code=error_code,
        provider=provider,
        model=model,
        latency_ms=latency_ms,
        rag_ms=rag_ms,
    )
