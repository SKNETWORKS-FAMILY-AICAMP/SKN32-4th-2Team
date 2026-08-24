"""벤치마크용 로컬 문서 로더.

**서비스가 아니라 측정 도구다.** 실제 RAG 서비스(Member C, port 8001)를 대체하지 않는다.

왜 필요한가
-----------
성능 측정에서 재고 싶은 것은 "LLM 이 주어진 근거를 얼마나 잘 쓰는가" 인데,
RAG 가 mock 이면 항상 같은 문서 2건만 와서 대부분의 질문에 근거가 없다.
그 상태로는 프롬프트 튜닝 효과(조문 인용, few-shot 등)를 측정할 수 없다.

그렇다고 실제 RAG 를 쓰기도 어렵다. 현재 검색에 30초가 걸려 34문항 한 조건에
17분이 든다. 튜닝 루프를 돌릴 수 없다.

그래서 여기서는 **검색이 완벽하다고 가정한다.** `questions.yaml` 에 질문별
정답 문서가 이미 라벨링되어 있으므로, 그 문서 **안에서만** 관련 구간을 찾는다.
28개 전체를 뒤지는 진짜 검색 문제와 달리, 정답 문서가 주어지면 훨씬 쉽다.

이렇게 하면 **RAG 성능과 LLM 성능이 분리된다.**
- 여기서 나온 점수 = 검색이 완벽할 때 LLM 이 낼 수 있는 상한선
- 나중에 실제 RAG 로 같은 문항을 돌린 점수와의 차이 = 검색이 깎아먹은 몫

주의: 이 값은 end-to-end 성능이 아니다. 보고서에 반드시 그렇게 명시할 것.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from app.domain import RetrievedChunk

# PDF 는 RAG 브랜치에만 있고 이 저장소에는 없다(6.7MB, 28개).
# 별도 폴더에 클론해 둔 경로를 기본값으로 쓰고, 환경변수로 덮어쓸 수 있게 한다.
DEFAULT_PDF_DIRS = [
    Path(os.getenv("BENCH_PDF_DIR", "")),
    Path(r"C:\Dev_Tools\rag_test\rag_only\RAG\res\pdf"),
    Path(__file__).resolve().parent.parent.parent / "RAG" / "res" / "pdf",
]

CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "corpus.json"

# 실제 RAG 와 같은 값으로 맞춘다. 청크 크기가 다르면 나중에 실제 RAG 결과와
# 비교할 때 조건이 달라져 해석이 어려워진다.
CHUNK_SIZE = 1000
SEPARATORS = ["\n제", "\n\n", "\n", " "]


@dataclass(slots=True)
class Chunk:
    file: str
    page: int  # 1-based (사람이 보는 번호)
    text: str


def _find_pdf_dir() -> Path:
    for d in DEFAULT_PDF_DIRS:
        if d and d.is_dir() and any(d.glob("*.pdf")):
            return d
    raise FileNotFoundError(
        "PDF 폴더를 찾지 못했습니다. BENCH_PDF_DIR 환경변수로 지정하세요.\n"
        "  예: BENCH_PDF_DIR=C:\\Dev_Tools\\rag_test\\rag_only\\RAG\\res\\pdf"
    )


def _split(text: str) -> list[str]:
    """구분자 우선순위대로 자른다. 법령이라 '\\n제' (조문 시작)를 최우선으로 둔다."""
    text = text.strip()
    if len(text) <= CHUNK_SIZE:
        return [text] if text else []

    for sep in SEPARATORS:
        if sep not in text:
            continue
        parts, buf = [], ""
        for piece in text.split(sep):
            candidate = (buf + sep + piece) if buf else piece
            if len(candidate) <= CHUNK_SIZE:
                buf = candidate
            else:
                if buf:
                    parts.append(buf)
                buf = piece
        if buf:
            parts.append(buf)
        if all(len(p) <= CHUNK_SIZE for p in parts):
            return [p.strip() for p in parts if p.strip()]

    # 어떤 구분자로도 안 나뉘면 길이로 자른다.
    return [text[i : i + CHUNK_SIZE].strip() for i in range(0, len(text), CHUNK_SIZE)]


# 법제처 PDF 는 페이지마다 머리말/꼬리말이 붙는다.
#   "법제처                    2                    국가법령정보센터"
#   "근로기준법 시행령"
# 이걸 그대로 두면 모든 청크 앞에 노이즈가 붙어 프롬프트를 낭비하고,
# 검색 점수도 왜곡된다(짧은 청크가 머리말만으로 점수를 얻는다).
_HEADER_PATTERNS = (
    re.compile(r"^\s*법제처\s*\d*\s*(국가법령정보센터)?\s*$"),
    re.compile(r"^\s*국가법령정보센터\s*$"),
    re.compile(r"^\s*-\s*\d+\s*/\s*\d+\s*-\s*$"),  # "-2/3-" 형태
)


def _clean_page(text: str) -> str:
    """머리말·꼬리말을 걷어내고 공백을 정리한다."""
    lines = []
    for line in text.split("\n"):
        if any(p.match(line) for p in _HEADER_PATTERNS):
            continue
        # 법제처 PDF 는 정렬용 공백이 수십 칸씩 들어간다
        line = re.sub(r"[ \t]{2,}", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _extract(pdf_path: Path) -> list[Chunk]:
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    chunks: list[Chunk] = []
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            text = _clean_page(page.extract_text() or "")
        except Exception:
            continue
        for piece in _split(text):
            # 공백을 뺀 실질 길이로 판단한다. 공백 패딩 때문에 빈 조각이 통과한다
            if len(re.sub(r"\s+", "", piece)) < 40:
                continue
            chunks.append(Chunk(file=pdf_path.name, page=page_no, text=piece))
    return chunks


def load_corpus(refresh: bool = False) -> dict[str, list[Chunk]]:
    """PDF 를 청크로 쪼개 파일명별로 묶는다. 결과는 캐시한다.

    28개 PDF 를 매번 파싱하면 벤치를 돌릴 때마다 수십 초를 버린다.
    """
    if not refresh and CACHE_PATH.exists():
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return {
            name: [Chunk(**c) for c in chunks] for name, chunks in raw.items()
        }

    pdf_dir = _find_pdf_dir()
    corpus: dict[str, list[Chunk]] = {}
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        corpus[pdf.name] = _extract(pdf)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(
            {n: [asdict(c) for c in cs] for n, cs in corpus.items()},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return corpus


_NON_WORD = re.compile(r"[\s\W_]+", re.UNICODE)


def _bigrams(text: str) -> set[str]:
    """한국어용 문자 2-gram.

    형태소 분석기 없이 조사 변화("연차를/연차가/연차는")에 견디려면 문자 n-gram 이
    가장 단순하고 효과적이다. 단어 단위로 자르면 "연차를" 과 "연차" 가 안 맞는다.
    """
    s = _NON_WORD.sub("", unicodedata.normalize("NFKC", text).lower())
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _score(query_grams: set[str], chunk_text: str) -> float:
    """질문의 어느 정도가 이 청크 안에 들어 있는가(coverage).

    처음에는 코사인 유사도를 썼는데 **짧은 청크가 부당하게 유리**했다.
    분모에 청크 길이가 들어가서, 머리말 몇 글자만 겹쳐도 점수가 높게 나왔다.

    여기서는 '질문 대비 겹침 비율' 만 본다. 청크 길이는 CHUNK_SIZE 로 이미
    제한돼 있어 길이 편차가 크지 않다.
    """
    grams = _bigrams(chunk_text)
    if not grams or not query_grams:
        return 0.0
    return len(query_grams & grams) / len(query_grams)


# 법령 파일명은 판본이 괄호로 붙는다: "5.근로기준법(법률).pdf", "...(시행령).pdf"
# 사내 문서는 괄호가 없다("직원인사규정 시행규칙.pdf" 처럼 같은 단어가 들어가도
# 괄호가 아니므로 걸리지 않는다).
_LAW_SUFFIX = re.compile(r"\((법률|시행령|시행규칙)\)")


def is_law(filename: str) -> bool:
    return bool(_LAW_SUFFIX.search(filename))


def search(
    query: str,
    files: list[str],
    top_k: int = 5,
    corpus: dict[str, list[Chunk]] | None = None,
    internal_quota: float = 0.5,
) -> list[RetrievedChunk]:
    """`files` 로 지정한 문서 **안에서만** 관련 구간을 찾는다.

    실제 RAG 처럼 전체 코퍼스를 뒤지지 않는다. 정답 문서가 주어졌다는 전제이므로
    이것은 '검색 성능' 이 아니라 '이상적 검색' 을 흉내내는 것이다.

    `files` 가 비면 빈 목록을 돌려준다 — 범위 밖 질문(out_of_scope)에서
    근거 없이 답하는지 보려면 문서가 없어야 한다.
    """
    if not files:
        return []

    corpus = corpus if corpus is not None else load_corpus()
    query_grams = _bigrams(query)

    scored: list[tuple[float, Chunk]] = []
    for name in files:
        for chunk in corpus.get(name, []):
            scored.append((_score(query_grams, chunk.text), chunk))

    scored.sort(key=lambda x: x[0], reverse=True)

    # 사내 규정에 자리를 먼저 배정한다.
    #
    # 그냥 점수순으로 뽑으면 법령이 거의 다 차지한다. 법령이 청크 450개인데
    # 사내 문서는 228개라 분량만으로 유리하기 때문이다. 의도한 게 아니라
    # 코퍼스 구성에서 오는 편향이다.
    #
    # 그런데 직원이 알아야 할 답은 대개 사내 규정에 있다. 법령은 최저 기준이고
    # 사내 규정이 그보다 유리한 경우가 많다 — 근로기준법은 연차 15일이지만
    # 복무규정 제20조는 3년 이상 재직 시 최대 25일까지 준다.
    #
    # 그래서 사내 문서에 `internal_quota` 만큼 자리를 예약하고, 남는 자리를
    # 점수순으로 채운다. 사내 문서가 부족하면 법령이 그 자리를 가져간다.
    internal = [(s, c) for s, c in scored if s > 0 and not is_law(c.file)]
    law = [(s, c) for s, c in scored if s > 0 and is_law(c.file)]

    reserved = min(len(internal), int(top_k * internal_quota + 0.5))
    picked = internal[:reserved] + law
    picked += internal[reserved:]

    out: list[RetrievedChunk] = []
    seen: set[tuple[str, int]] = set()
    for score, chunk in picked:
        key = (chunk.file, chunk.page)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            RetrievedChunk(
                original_file_name=chunk.file,
                content=chunk.text,
                doc_id=None,
                page=chunk.page,
                score=round(score, 4),
            )
        )
        if len(out) >= top_k:
            break
    return out
