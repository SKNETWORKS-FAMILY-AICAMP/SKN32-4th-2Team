"""RAG 서비스(port 8001, Member C 담당) HTTP 클라이언트.

설계 원칙: **RAG 실패로 챗봇이 죽지 않는다.**
검색이 안 되면 문서 없이라도 답하는 편이 500을 던지는 것보다 사용자에게 낫다.
따라서 이 모듈은 예외를 밖으로 던지지 않고 (검색결과, degraded) 튜플을 돌려준다.
"""

from __future__ import annotations

import logging
import ntpath
import posixpath
import time

import httpx

from app.config import get_settings
from app.domain import RetrievedChunk

logger = logging.getLogger(__name__)

SEARCH_PATH = "/api/search"

_client: httpx.AsyncClient | None = None

# RAG_MODE=mock 일 때 쓰는 고정 응답.
# **실제 RAG 서비스가 돌려주는 형태 그대로** 둔다 (metadata.source 가 절대경로,
# page 는 0부터, doc_id/score 없음). 그래야 mock 으로 돌린 테스트가 아래 파싱
# 경로를 실제와 똑같이 통과한다.
_MOCK_RESULTS: list[dict] = [
    {
        "content": (
            "제60조(연차 유급휴가) ① 사용자는 1년간 80퍼센트 이상 출근한 근로자에게 "
            "15일의 유급휴가를 주어야 한다."
        ),
        "metadata": {
            "source": r"D:\study\SKN32-3rd-2Team\rag\res\pdf\5.근로기준법(법률).pdf",
            "page": 22,
            "page_label": "23",
            "total_pages": 40,
        },
    },
    {
        "content": "제12조(휴가의 신청) 직원이 휴가를 사용하려는 경우 사전에 결재권자의 승인을 받아야 한다.",
        "metadata": {
            "source": r"D:\study\SKN32-3rd-2Team\rag\res\pdf\복무규정.pdf",
            "page": 4,
            "page_label": "5",
            "total_pages": 12,
        },
    },
]


def _basename(path: str) -> str:
    """절대경로에서 파일명만 뽑는다.

    RAG 가 주는 `metadata.source` 는 그 사람 PC 의 절대경로다.
        D:\\study\\sk_playdata\\personal\\...\\res\\pdf\\복무규정.pdf
    그대로 화면에 뿌리면 **다른 팀원의 로컬 경로가 사용자에게 노출**되므로
    반드시 파일명만 남긴다. 서버가 Linux 여도 Windows 경로가 올 수 있으니
    두 구분자를 모두 처리한다.
    """
    return ntpath.basename(posixpath.basename(path or "")) or ""


def _file_name_of(result: dict, metadata: dict) -> str:
    """출처로 표시할 파일명을 뽑는다.

    RAG 쪽 응답 필드가 여러 번 바뀌었으므로 알려진 이름을 모두 받는다.
    지금(하이브리드 검색 도입 후)은 `metadata.source_file` 로 온다.
    마지막 수단인 `metadata.source` 는 **그 사람 PC 의 절대경로**라
        C:\\Dev_Tools\\rag_test\\rag_only\\RAG\\res/pdf/복무규정.pdf
    그대로 뿌리면 로컬 경로가 사용자에게 노출되므로 파일명만 남긴다.
    """
    return str(
        result.get("original_file_name")
        or result.get("file_name")
        or metadata.get("source_file")
        or metadata.get("original_file_name")
        or _basename(metadata.get("source", ""))
        or ""
    )


def _page_of(result: dict, metadata: dict) -> int | None:
    """사람이 읽는 페이지 번호(1부터)를 뽑는다.

    RAG 가 어느 표기를 주는지가 버전마다 달라서 1-based 인 것부터 확인한다.
    `metadata.page` 는 0-based 라 그대로 쓰면 화면에 'p.0' 이 뜬다.
    """
    if result.get("page") is not None:
        return result["page"]
    for key in ("page_number", "page_label"):
        value = metadata.get(key)
        if value is not None and str(value).isdigit():
            return int(value)
    page = metadata.get("page")
    return page + 1 if isinstance(page, int) else None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            base_url=settings.rag_base_url,
            timeout=settings.rag_timeout_sec,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _relevant(results: list[dict], min_score: float) -> list[dict]:
    """관련도가 낮은 결과를 걷어낸다.

    RAG 는 관련 문서가 없어도 top_k 를 무관한 청크로 채워 돌려준다. 그대로
    프롬프트에 넣으면 모델이 근거가 있다고 착각하고 문서에 없는 수치를 지어낸다.
    근거 없이 그럴듯한 답을 하느니 "찾을 수 없습니다" 가 낫다.

    점수가 아예 없는 응답(구버전 RAG, mock)에서는 아무것도 거르지 않는다.
    거르는 기준이 없는데 전부 버리면 검색이 통째로 죽는다.
    """
    if min_score <= 0:
        return results
    scored = [r for r in results if r.get("rerank_score") is not None]
    if not scored:
        return results
    kept = [r for r in scored if r["rerank_score"] >= min_score]
    if len(kept) < len(scored):
        logger.info(
            "관련도 낮은 검색 결과 %d/%d 건 제외 (기준 %.3f)",
            len(scored) - len(kept),
            len(scored),
            min_score,
        )
    return kept


def _to_chunks(results: list[dict], top_k: int) -> list[RetrievedChunk]:
    """RAG 응답을 내부 모델로 바꾸면서 중복을 제거한다.

    필드가 최상위에 있든(`original_file_name`) metadata 안에 있든(`source`) 모두 받는다.
    RAG 쪽이 나중에 `doc_id`/`score` 를 최상위로 올려도 이 함수는 그대로 동작한다.

    RAG 가 돌려주는 단위는 '문서'가 아니라 '청크'라, 한 페이지에서 인접한 청크가
    여러 개 걸리면 같은 (파일, 페이지)가 중복으로 온다. 그대로 두면 답변 하단에
    "복무규정.pdf p.5"가 두 번 표시되므로 여기서 합친다.
    페이지가 다르면 서로 다른 근거이므로 남긴다. 순서(관련도 순)는 유지한다.

    RAG 가 `top_k` 파라미터를 받지 않으므로 개수 제한도 여기서 건다.
    """
    chunks: list[RetrievedChunk] = []
    seen: set[tuple[str, int | None]] = set()
    for r in results:
        metadata = r.get("metadata") or {}
        name = _file_name_of(r, metadata)
        if not name:
            continue  # 문서명이 없으면 출처로 표시할 수 없다
        page = _page_of(r, metadata)
        key = (name, page)
        if key in seen:
            continue
        seen.add(key)
        # doc_id 는 문자열("10")로 오기도 한다. 스키마가 int 라 맞춰준다.
        doc_id = r.get("doc_id") or metadata.get("doc_id")
        if isinstance(doc_id, str):
            doc_id = int(doc_id) if doc_id.isdigit() else None
        # 리랭커 점수가 있으면 그쪽이 최종 관련도다(faiss/bm25 는 중간 점수).
        score = r.get("rerank_score")
        if score is None:
            score = r.get("score") or metadata.get("score")
        chunks.append(
            RetrievedChunk(
                original_file_name=name,
                content=str(r.get("content") or ""),
                doc_id=doc_id,
                page=page,
                score=score,
            )
        )
        if len(chunks) >= top_k:
            break
    return chunks


async def search(query: str, top_k: int | None = None) -> tuple[list[RetrievedChunk], bool, int]:
    """관련 문서 조각을 검색한다.

    Returns:
        (chunks, degraded, elapsed_ms) — degraded=True 면 검색 실패로 문서 없이 진행해야 함.
    """
    settings = get_settings()
    k = top_k or settings.rag_top_k
    started = time.perf_counter()

    if settings.rag_mode == "mock":
        return _to_chunks(_MOCK_RESULTS, k), False, 0

    try:
        # RAG 는 query 하나만 받는다. top_k 는 지원하지 않아 개수 제한은 우리 쪽에서 건다.
        resp = await get_client().post(SEARCH_PATH, json={"query": query})
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        # 로그만 남기고 degraded 로 계속 간다.
        logger.warning("RAG 검색 실패 — 문서 없이 응답합니다: %s", exc)
        return [], True, int((time.perf_counter() - started) * 1000)

    results = payload.get("results", []) if isinstance(payload, dict) else []
    results = _relevant(results, settings.rag_min_score)
    # 관련 문서가 하나도 없어도 degraded 가 아니다 — 검색은 정상 동작했고,
    # 답이 코퍼스에 없을 뿐이다. degraded 는 RAG 호출 자체가 실패했을 때만 쓴다.
    return _to_chunks(results, k), False, int((time.perf_counter() - started) * 1000)


async def health() -> str:
    """/health 표시용: up | down | mock"""
    settings = get_settings()
    if settings.rag_mode == "mock":
        return "mock"
    try:
        resp = await get_client().get("/health", timeout=1.0)
        return "up" if resp.status_code < 500 else "down"
    except httpx.HTTPError:
        return "down"
