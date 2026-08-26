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
from collections.abc import Sequence

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

    RAG 가 어느 표기를 주는지가 버전마다 달라서 의미가 명확한 필드부터 확인한다.

    - ``page_number``/``page_label``: 사람이 읽는 1-based 번호
    - ``page_index``: 명시적인 0-based 인덱스
    - 최상위 ``page``: 구버전의 1-based 번호(0은 첫 페이지로 보정)
    - ``metadata.page``: LangChain/PyPDFLoader의 0-based 인덱스

    현재 RAG 전처리의 구버전은 PyPDFLoader의 0-based ``metadata.page``을
    ``metadata.page_number``로 그대로 복사했다. 두 값이 같으면 구버전으로
    보고 한 페이지를 더한다. 그래서 첫 페이지만 p.0을 막는 데 그치지 않고
    뒤 페이지의 off-by-one도 함께 고친다. 음수나 숫자가 아닌 값은 표시하지
    않아 잘못된 ``p.-1``이 나가지 않게 한다.
    """

    def _as_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
        return None

    def _one_based(value: object) -> int | None:
        number = _as_int(value)
        if number is None or number < 0:
            return None
        return max(1, number)

    def _zero_based(value: object) -> int | None:
        index = _as_int(value)
        if index is None or index < 0:
            return None
        return index + 1

    # 새 계약인 최상위 필드는 이름만으로 기준을 알 수 있으므로 먼저 사용한다.
    for key in ("page_number", "page_label"):
        page = _one_based(result.get(key))
        if page is not None:
            return page
    page = _zero_based(result.get("page_index"))
    if page is not None:
        return page

    # PDF가 붙인 실제 페이지 라벨과 명시적인 인덱스도 우선한다.
    page = _one_based(metadata.get("page_label"))
    if page is not None:
        return page
    page = _zero_based(metadata.get("page_index"))
    if page is not None:
        return page

    metadata_number = _as_int(metadata.get("page_number"))
    metadata_index = _as_int(metadata.get("page"))
    if metadata_number is not None and metadata_number >= 0:
        if metadata_index is not None and metadata_number == metadata_index:
            # 구버전 RAG가 0-based page를 page_number로 그대로 복사한 경우.
            return metadata_index + 1
        return max(1, metadata_number)

    # 구버전의 최상위 page는 사람이 읽는 번호로 사용했다. 다만 실제 응답에서
    # page=0도 관측됐으므로 0만 첫 페이지로 안전하게 보정한다.
    page = _one_based(result.get("page"))
    if page is not None:
        return page

    # LangChain/PyPDFLoader metadata.page는 0-based다.
    return _zero_based(metadata.get("page"))


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
    """RAG 응답을 관련도 순서 그대로 내부 청크 모델로 바꾼다.

    필드가 최상위에 있든(`original_file_name`) metadata 안에 있든(`source`) 모두 받는다.
    RAG 쪽이 나중에 `doc_id`/`score` 를 최상위로 올려도 이 함수는 그대로 동작한다.

    RAG 가 돌려주는 단위는 '문서'가 아니라 '청크'다. 같은 페이지의 서로 다른
    청크에도 별개의 조문이나 표 행이 있을 수 있으므로 프롬프트용 청크는 합치지
    않는다. 화면의 출처 목록만 합쳐야 할 때는 ``unique_source_chunks``를 쓴다.

    RAG 가 `top_k` 파라미터를 받지 않으므로 개수 제한도 여기서 건다. 문서명이
    없는 잘못된 결과는 건너뛰되, 나머지는 입력 순서 그대로 최대 ``top_k``개다.
    """
    chunks: list[RetrievedChunk] = []
    for r in results:
        metadata = r.get("metadata") or {}
        name = _file_name_of(r, metadata)
        if not name:
            continue  # 문서명이 없으면 출처로 표시할 수 없다
        page = _page_of(r, metadata)
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
                article=(str(metadata.get("article")) if metadata.get("article") else None),
                section_type=(
                    str(metadata.get("section_type")) if metadata.get("section_type") else None
                ),
                document_title=(
                    str(metadata.get("document_title"))
                    if metadata.get("document_title")
                    else None
                ),
                authority=(str(metadata.get("authority")) if metadata.get("authority") else None),
                audience=tuple(
                    str(value)
                    for value in (
                        metadata.get("audience")
                        if isinstance(metadata.get("audience"), (list, tuple))
                        else [metadata.get("audience")]
                    )
                    if value
                ),
            )
        )
        if len(chunks) >= top_k:
            break
    return chunks


def unique_source_chunks(chunks: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
    """UI 출처용으로 같은 파일·페이지·조문을 하나만 남긴다.

    답변 프롬프트에는 모든 청크가 필요하지만 화면에 ``규정.pdf p.5``가 반복될
    필요는 없다. 첫 청크(검색 관련도가 가장 높은 청크)를 대표로 남기며 입력
    순서를 보존한다. ``doc_id``가 다르면 같은 파일명·페이지여도 별도 문서이므로
    합치지 않는다. 같은 페이지에 서로 다른 조문이 함께 있을 수 있으므로
    ``article``까지 같은 경우에만 합친다. 그래야 화면에서 근거 조문 하나가
    조용히 사라지지 않는다.
    """
    unique: list[RetrievedChunk] = []
    seen: set[tuple[int | None, str, int | None, str | None]] = set()
    for chunk in chunks:
        key = (chunk.doc_id, chunk.original_file_name, chunk.page, chunk.article)
        if key in seen:
            continue
        seen.add(key)
        unique.append(chunk)
    return unique


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
