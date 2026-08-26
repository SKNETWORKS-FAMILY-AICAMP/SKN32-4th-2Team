import math
import os
import re
from typing import List, Optional, Any

try:
    # ``cd RAG; python app.py``로 실행할 때의 기존 import 경로.
    from document_metadata import derive_document_metadata
except ModuleNotFoundError:  # pragma: no cover - 패키지형 import 호환
    # 저장소 루트에서 ``import RAG.rag_pipeline``로 검사할 때도 동작하게 한다.
    from .document_metadata import derive_document_metadata


_embedding_model = None
_reranker_model = None


def _device() -> str:
    """RAG 실행 장치를 반환한다.

    기본값 ``auto``는 CUDA 지원 PyTorch와 GPU를 사용할 수 있을 때 CUDA를,
    그 외에는 CPU를 선택한다. cpu/cuda 강제값은 성능 비교와 문제 진단용이다.
    """
    requested = os.getenv("RAG_DEVICE", "auto").strip().lower() or "auto"
    if requested == "cpu":
        return "cpu"

    is_cuda = requested == "cuda" or re.fullmatch(r"cuda:\d+", requested)
    if requested != "auto" and not is_cuda:
        raise ValueError("RAG_DEVICE must be one of: auto, cpu, cuda, cuda:<index>")

    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
    except ImportError as exc:
        if is_cuda:
            raise RuntimeError(
                "RAG_DEVICE requests CUDA, but PyTorch is not installed"
            ) from exc
        return "cpu"

    if requested == "auto":
        return "cuda" if cuda_available else "cpu"
    if not cuda_available:
        raise RuntimeError(
            f"RAG_DEVICE={requested}, but CUDA is not available in this PyTorch runtime"
        )
    if ":" in requested:
        device_index = int(requested.split(":", 1)[1])
        if device_index >= torch.cuda.device_count():
            raise RuntimeError(
                f"RAG_DEVICE={requested}, but only {torch.cuda.device_count()} CUDA device(s) are available"
            )
    return requested


def get_runtime_device() -> str:
    """배포 상태 확인용 공개 장치 resolver."""
    return _device()


class DocumentLike:
    def __init__(self, page_content: str, metadata: Optional[dict] = None):
        self.page_content = page_content
        self.metadata = metadata or {}


try:
    from langchain_core.documents import Document as LangchainDocument
except Exception:  # pragma: no cover - fallback for lightweight test environments
    LangchainDocument = DocumentLike


# 조문 머리(예: 제60조(연차 유급휴가))를 청크 앞에 보강한다. 조문 중간에서
# 잘린 청크도 LLM이 근거 조문을 식별할 수 있게 하기 위한 메타데이터다.
_ARTICLE_HEAD = re.compile(
    r"제[ \t]*"
    r"(?P<number>[0-9０-９](?:[ \t]*[0-9０-９])*)[ \t]*조"
    r"(?:[ \t]*(?:의[ \t]*)?(?P<sub_number>[0-9０-９](?:[ \t]*[0-9０-９])*))?"
    r"[ \t]*[\(（][ \t]*(?P<title>[^()（）\n]{1,80}?)[ \t]*[\)）]"
)

# 삭제 조문처럼 제목 괄호가 없는 머리도 경계로 유지한다. 본문 인용을 조문
# 머리로 오인하지 않도록 삭제/개정 표식 또는 줄 끝이 바로 뒤따를 때만 허용한다.
_BARE_ARTICLE_HEAD = re.compile(
    r"제[ \t]*"
    r"(?P<number>[0-9０-９](?:[ \t]*[0-9０-９])*)[ \t]*조"
    r"(?:[ \t]*(?:의[ \t]*)?(?P<sub_number>[0-9０-９](?:[ \t]*[0-9０-９])*))?"
    r"(?=[ \t]*(?:[<〈\[]|$|\n))",
    re.MULTILINE,
)

# 부칙/별표/별지/서식은 앞 조문의 적용 범위를 끝내는 독립 구조다. 줄 머리
# 패턴으로 제한하여 본문의 "별표에 따른다" 같은 문장은 경계로 오인하지 않는다.
_LEGAL_BOUNDARY = re.compile(
    r"(?im)^[ \t]*(?P<heading>"
    r"[\[【\(（][ \t]*(?:"
    r"별[ \t]*(?:표|지)(?:[ \t]*(?:제[ \t]*)?[0-9０-９]+(?:[ \t]*의[ \t]*[0-9０-９]+)?[ \t]*(?:호)?)?(?:[ \t]*서[ \t]*식)?"
    r"|서[ \t]*식(?:[ \t]*(?:제[ \t]*)?[0-9０-９]+(?:-[0-9０-９]+)?[ \t]*(?:호)?)?"
    r"|제[ \t]*[0-9０-９]+(?:-[0-9０-９]+)?[ \t]*호[ \t]*서[ \t]*식"
    r")[ \t]*[\]】\)）]"
    r"|부[ \t]*칙(?:[ \t]*[<〈].{1,40}[>〉])?(?=[ \t]*(?:$|\n))"
    r"|별[ \t]*(?:표|지)(?![가-힣])(?:[ \t]*(?:제[ \t]*)?[0-9０-９]+(?:[ \t]*의[ \t]*[0-9０-９]+)?[ \t]*(?:호)?)?[^\n]{0,60}(?=[ \t]*(?:$|\n))"
    r"|제[ \t]*[0-9０-９]+[ \t]*호[ \t]*서[ \t]*식(?![가-힣])[^\n]{0,60}(?=[ \t]*(?:$|\n))"
    r"|서[ \t]*식(?![가-힣])(?:[ \t]*(?:제[ \t]*)?[0-9０-９]+[ \t]*(?:호)?)?[^\n]{0,60}(?=[ \t]*(?:$|\n))"
    r")"
)

_TABLE_HEADER_TERMS = (
    "구분",
    "항목",
    "내용",
    "기준",
    "처분",
    "징계",
    "비고",
    "횟수",
    "대상",
    "구성",
    "혈중알코올농도",
)


def _canonical_article_head(match: re.Match) -> str:
    number = re.sub(r"\s+", "", match.group("number"))
    sub_number = match.group("sub_number")
    compact_sub_number = re.sub(r"\s+", "", sub_number) if sub_number else ""
    suffix = f"의{compact_sub_number}" if compact_sub_number else ""
    title = re.sub(r"\s+", " ", match.group("title")).strip()
    return f"제{number}조{suffix}({title})"


def _canonical_bare_article_head(match: re.Match) -> str:
    number = re.sub(r"\s+", "", match.group("number"))
    sub_number = match.group("sub_number")
    compact_sub_number = re.sub(r"\s+", "", sub_number) if sub_number else ""
    suffix = f"의{compact_sub_number}" if compact_sub_number else ""
    return f"제{number}조{suffix}"


def _article_head_matches(text: str) -> List[tuple[int, int, str]]:
    matches = [
        (match.start(), match.end(), _canonical_article_head(match))
        for match in _ARTICLE_HEAD.finditer(text)
    ]
    matches.extend(
        (match.start(), match.end(), _canonical_bare_article_head(match))
        for match in _BARE_ARTICLE_HEAD.finditer(text)
    )
    return sorted(matches, key=lambda item: item[0])


def _normalize_table_line(line: str) -> tuple[str, bool]:
    """PDF가 공백/탭으로 추출한 표의 열 경계를 가벼운 구분자로 보존한다."""
    if "|" in line:
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
    elif "\t" in line or re.search(r"\S[ ]{2,}\S", line):
        cells = [cell.strip() for cell in re.split(r"\t+|[ ]{2,}", line) if cell.strip()]
    else:
        return re.sub(r"[ \t]+", " ", line).strip(), False

    if len(cells) < 2:
        return re.sub(r"[ \t]+", " ", line).strip(), False
    return " | ".join(re.sub(r"[ \t]+", " ", cell) for cell in cells), True


def _normalize_whitespace(text: str) -> str:
    """불필요한 PDF 줄바꿈은 합치되 법령/표 구조 줄바꿈은 보존한다."""
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    normalized_lines: List[tuple[str, bool]] = []
    blank_pending = False
    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            blank_pending = True
            continue
        if re.fullmatch(r"(?i)page[ \t]*\d+", stripped):
            continue

        # OCR이 조문 번호/괄호 사이에 삽입한 공백과 전각 괄호를 표준화한다.
        canonical_line = _ARTICLE_HEAD.sub(_canonical_article_head, stripped)
        canonical_line = _BARE_ARTICLE_HEAD.sub(_canonical_bare_article_head, canonical_line)
        line, is_table_row = _normalize_table_line(canonical_line)
        article_matches = _article_head_matches(line)
        is_structural = bool(article_matches or _LEGAL_BOUNDARY.match(line))

        # 한 줄로 뭉친 OCR 결과에서도 제목이 붙은 새 조문 앞은 분리한다.
        parts: List[str] = []
        cursor = 0
        for start, end, _head in article_matches:
            if start > cursor:
                prefix = line[cursor:start].strip()
                if prefix:
                    parts.append(prefix)
            parts.append(line[start:end])
            cursor = end
        if cursor and cursor < len(line):
            suffix = line[cursor:].strip()
            if suffix:
                parts[-1] = f"{parts[-1]} {suffix}"
        elif not parts:
            parts = [line]

        for part_index, part in enumerate(parts):
            preserve_break = is_structural or is_table_row or part_index > 0
            if blank_pending and normalized_lines:
                normalized_lines.append(("", True))
            normalized_lines.append((part, preserve_break))
            blank_pending = False

    output = ""
    previous_preserved = False
    for line, preserve_break in normalized_lines:
        if not line:
            if output and not output.endswith("\n\n"):
                output = output.rstrip() + "\n\n"
            previous_preserved = True
            continue
        if not output:
            output = line
        elif preserve_break or previous_preserved:
            output = output.rstrip() + "\n" + line
        else:
            output = output.rstrip() + " " + line
        previous_preserved = preserve_break

    output = re.sub(r"\n{3,}", "\n\n", output)
    return output.strip()


def _article_heads(text: str) -> List[tuple]:
    """본문에서 (문자 위치, 조문 머리) 목록을 추출한다."""
    return [(start, head) for start, _end, head in _article_head_matches(text)]


def _head_for(offset: int, heads: List[tuple]) -> Optional[str]:
    """지정 위치보다 앞에 있는 가장 가까운 조문 머리를 반환한다."""
    found = None
    for position, head in heads:
        if position <= offset:
            found = head
        else:
            break
    return found


def _boundary_kind(heading: str) -> str:
    compact = re.sub(r"[\s\[\]【】()（）]", "", heading)
    if compact.startswith("부칙"):
        return "supplementary"
    if compact.startswith("별표"):
        return "appendix_table"
    if compact.startswith("별지"):
        return "attachment"
    return "form"


def _structure_events(text: str) -> List[tuple[int, int, str, str]]:
    """법령 구조 변경 이벤트를 위치 순으로 반환한다.

    동일 위치라면 경계를 먼저 적용한다. 따라서 별표/서식으로 넘어간 청크에
    직전 본문 조문이 잘못 상속되지 않는다.
    """
    events: List[tuple[int, int, str, str]] = []
    for match in _LEGAL_BOUNDARY.finditer(text):
        heading = match.group("heading").strip()
        events.append((match.start(), 0, "boundary", _boundary_kind(heading)))
    for position, head in _article_heads(text):
        events.append((position, 1, "article", head))
    return sorted(events, key=lambda item: (item[0], item[1]))


def _extract_table_header(text: str) -> Optional[str]:
    candidates = []
    for line in text.splitlines():
        if " | " not in line:
            continue
        score = sum(term in line for term in _TABLE_HEADER_TERMS)
        if score:
            candidates.append((score, line.strip()))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _is_meaningful_chunk(content: str, *, min_length: int = 80) -> bool:
    if not content:
        return False
    cleaned = re.sub(r"\s+", " ", content).strip()
    if len(cleaned) < min_length:
        return False
    if re.fullmatch(r"[\W_]+", cleaned):
        return False
    return True


def _normalize_korean_term(text: str) -> str:
    if not text:
        return ""

    cleaned = text.strip().lower()
    if not cleaned:
        return ""

    endings = ["은", "는", "이", "가", "을", "를", "의", "에", "에서", "로", "으로", "와", "과", "도", "만"]
    for ending in endings:
        if cleaned.endswith(ending) and len(cleaned) > len(ending):
            cleaned = cleaned[:-len(ending)]
            break

    return cleaned


_ANNUAL_LEAVE_COUNT_TERMS = ("며칠", "몇일", "일수", "사용가능", "쓸수", "최대")
_ANNUAL_LEAVE_SEARCH_CONTEXT = "복무규정 연차휴가 사용 가능 일수 재직기간 출근율"


def normalize_search_query(text: str) -> str:
    """원문 표현을 보존하면서 짧은 생활형 질의에 규정 검색 문맥을 보강한다."""

    normalized = " ".join(str(text or "").split())
    joined = re.sub(r"\s+", "", normalized)
    if (
        ("연차" in joined or "연가" in joined)
        and "수당" not in joined
        and any(term in joined for term in _ANNUAL_LEAVE_COUNT_TERMS)
        and not all(term in normalized for term in ("복무규정", "재직기간", "출근율"))
    ):
        normalized = f"{normalized} {_ANNUAL_LEAVE_SEARCH_CONTEXT}"
    return " ".join(normalized.split())


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    tokens = re.findall(r"[가-힣a-zA-Z0-9]+", text.lower())
    return [_normalize_korean_term(token) for token in tokens if _normalize_korean_term(token)]


def _calculate_bm25_scores(query: str, documents: List[str]) -> List[float]:
    query_terms = _tokenize(query)
    tokenized_docs = [_tokenize(doc) for doc in documents]

    if not query_terms or not tokenized_docs:
        return [0.0 for _ in documents]

    try:
        from rank_bm25 import BM25Okapi

        bm25 = BM25Okapi(tokenized_docs)
        scores = bm25.get_scores(query_terms)
        return [float(score) for score in scores]
    except Exception:
        pass

    doc_freq: dict[str, int] = {}
    for terms in tokenized_docs:
        unique_terms = set(terms)
        for term in unique_terms:
            doc_freq[term] = doc_freq.get(term, 0) + 1

    n_docs = len(tokenized_docs)
    avg_len = sum(len(terms) for terms in tokenized_docs) / max(1, n_docs)
    scores: List[float] = []

    for terms in tokenized_docs:
        doc_len = len(terms)
        score = 0.0
        for term in query_terms:
            if term not in doc_freq:
                continue
            freq = terms.count(term)
            if freq == 0:
                continue
            idf = math.log((n_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5) + 1.0)
            numerator = freq * (1.2 + 1.0)
            denominator = freq + 1.2 * (1.0 - 0.75 + 0.75 * (doc_len / max(avg_len, 1)))
            score += idf * (numerator / denominator)
        scores.append(score)

    return scores


def _metadata_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _resolve_page_numbers(metadata: dict, fallback_index: int) -> tuple[int, int]:
    """0-base ``page_index``와 1-base ``page_number``를 명시적으로 분리한다.

    PyPDFLoader의 ``page``는 0-base지만 기존 데이터에는 1-base 값도 있어 현재
    목록 위치와 비교해 두 형식을 모두 받아들인다. 명시 필드는 항상 우선한다.
    """
    explicit_index = _metadata_int(metadata.get("page_index"))
    explicit_number = _metadata_int(metadata.get("page_number"))
    legacy_page = _metadata_int(metadata.get("page"))

    if explicit_index is not None and explicit_index >= 0:
        page_index = explicit_index
    elif legacy_page is not None and legacy_page >= 0:
        if explicit_number is not None and legacy_page == explicit_number:
            page_index = max(legacy_page - 1, 0)
        elif explicit_number is not None and legacy_page + 1 == explicit_number:
            page_index = legacy_page
        elif legacy_page == fallback_index:
            page_index = legacy_page
        elif legacy_page == fallback_index + 1:
            page_index = max(legacy_page - 1, 0)
        else:
            # PyPDFLoader 계약을 기본값으로 삼는다.
            page_index = legacy_page
    elif explicit_number is not None and explicit_number > 0:
        page_index = explicit_number - 1
    else:
        page_index = fallback_index

    if explicit_number is not None and explicit_number > 0:
        page_number = explicit_number
    else:
        page_number = page_index + 1
    return page_index, page_number


def preprocess_pages(pages: List[Any]) -> List[Any]:
    documents = []
    for idx, page in enumerate(pages):
        raw_text = getattr(page, "page_content", "") or ""
        cleaned_text = _normalize_whitespace(raw_text)
        if not cleaned_text:
            continue

        metadata = dict(getattr(page, "metadata", {}) or {})
        page_index, page_number = _resolve_page_numbers(metadata, idx)
        metadata["page_index"] = page_index
        metadata["page_number"] = page_number
        # 기존 소비자는 page를 PyPDFLoader와 같은 0-base 인덱스로 계속 읽는다.
        metadata["page"] = page_index
        metadata.setdefault("source_file", os.path.basename(str(metadata.get("source", "unknown.pdf"))))
        # 직군·문서 권위를 모델의 본문 추측에 맡기지 않고 파일 단위 메타데이터로
        # 보존한다. 불명확한 문서는 audience=전체라 검색에서 잘못 제외되지 않는다.
        for key, value in derive_document_metadata(str(metadata["source_file"])).items():
            metadata.setdefault(key, value)

        documents.append(LangchainDocument(page_content=cleaned_text, metadata=metadata))

    return documents


def _build_structured_sections(documents: List[Any]) -> List[Any]:
    """페이지를 조문과 부속 구조 단위 문서로 나눠 splitter의 재병합을 막는다."""
    sections: List[Any] = []
    state_by_source: dict[str, tuple[Optional[str], str, Optional[str]]] = {}

    for doc in documents:
        metadata = dict(getattr(doc, "metadata", {}) or {})
        source_key = str(metadata.get("source_file", ""))
        current_article, current_section, current_table_header = state_by_source.get(
            source_key, (None, "main", None)
        )
        text = getattr(doc, "page_content", "") or ""
        cursor = 0

        def append_section(section_text: str, article: Optional[str], section_type: str) -> None:
            nonlocal current_table_header
            section_text = section_text.strip()
            if not section_text:
                return
            section_metadata = metadata.copy()
            section_metadata["article"] = article
            section_metadata["section_type"] = section_type
            table_header = _extract_table_header(section_text)
            if table_header:
                current_table_header = table_header
            if current_table_header and " | " in section_text:
                section_metadata["table_header"] = current_table_header
            sections.append(
                LangchainDocument(page_content=section_text, metadata=section_metadata)
            )

        for position, _priority, event_type, value in _structure_events(text):
            if position > cursor:
                append_section(text[cursor:position], current_article, current_section)
            if event_type == "boundary":
                current_article = None
                current_section = value
                current_table_header = None
            else:
                current_article = value
                if current_section not in {"appendix_table", "form"}:
                    current_table_header = None
            cursor = position

        append_section(text[cursor:], current_article, current_section)
        state_by_source[source_key] = (
            current_article,
            current_section,
            current_table_header,
        )

    return sections


def _fallback_split_documents(
    documents: List[Any], *, chunk_size: int, chunk_overlap: int
) -> List[Any]:
    """langchain splitter를 불러오지 못한 경량 환경용 크기 제한 분할기."""
    chunks: List[Any] = []
    safe_size = max(1, chunk_size)
    safe_overlap = max(0, min(chunk_overlap, safe_size - 1))
    for doc in documents:
        text = getattr(doc, "page_content", "") or ""
        start = 0
        while start < len(text):
            end = min(len(text), start + safe_size)
            if end < len(text):
                search_from = start + max(1, safe_size // 2)
                split_at = max(text.rfind("\n", search_from, end), text.rfind(" ", search_from, end))
                if split_at > start:
                    end = split_at
            content = text[start:end].strip()
            if content:
                chunk_metadata = dict(getattr(doc, "metadata", {}) or {})
                chunk_metadata["start_index"] = start
                chunks.append(
                    LangchainDocument(page_content=content, metadata=chunk_metadata)
                )
            if end >= len(text):
                break
            start = max(start + 1, end - safe_overlap)
    return chunks


def build_chunks_from_pages(
    pages: List[Any],
    *,
    chunk_size: int = 400,
    chunk_overlap: int = 80,
    separators: Optional[List[str]] = None,
) -> List[Any]:
    documents = preprocess_pages(pages)
    if not documents:
        return []

    # 조문/부속 구조를 먼저 별도 Document로 만든다. Recursive splitter는 서로
    # 다른 Document를 다시 합치지 않으므로 작은 조문도 다음 조문과 섞이지 않는다.
    structured_documents = _build_structured_sections(documents)

    if separators is None:
        separators = ["\n\n", "\n", " ", ""]

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
            add_start_index=True,
        )
        chunks = splitter.split_documents(structured_documents)
    except Exception:
        chunks = _fallback_split_documents(
            structured_documents,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    cleaned_chunks: List[Any] = []
    seen_signatures = set()
    min_chunk_length = int(os.getenv("RAG_MIN_CHUNK_LENGTH", "80"))

    for idx, chunk in enumerate(chunks):
        content = _normalize_whitespace(getattr(chunk, "page_content", "") or "")
        metadata = dict(getattr(chunk, "metadata", {}) or {})
        # 구조를 먼저 나누면 짧지만 유효한 조문/표 행이 생길 수 있다. 기존 80자
        # 노이즈 필터 때문에 이 근거가 통째로 사라지지 않도록 구조 청크만 완화한다.
        structured_minimum = min_chunk_length
        if metadata.get("article") or metadata.get("section_type") != "main":
            structured_minimum = min(20, min_chunk_length)
        if not _is_meaningful_chunk(content, min_length=structured_minimum):
            continue

        article = metadata.get("article")

        table_header = metadata.get("table_header")
        if table_header and " | " in content and table_header not in content:
            content = f"[표 머리] {table_header}\n{content}"

        # 청크의 시작 조문을 확실히 남긴다. 본문 뒤에 다른 조문이 있어도
        # 앞부분의 근거를 그 다른 조문으로 잘못 인용하지 않게 한다.
        content_article_heads = _article_head_matches(content.lstrip())
        if (
            article
            and os.getenv("RAG_ARTICLE_HEAD", "1") != "0"
            and not (content_article_heads and content_article_heads[0][0] == 0)
        ):
            content = f"[{article}] {content}"

        metadata.update({
            "chunk_id": idx,
            "char_count": len(content),
            "section_heading": content.splitlines()[0][:80] if content.splitlines() else content[:80],
            "source_file": metadata.get("source_file", "unknown.pdf"),
            "page_index": metadata.get("page_index", 0),
            "page_number": metadata.get("page_number", int(metadata.get("page_index", 0)) + 1),
            "is_legal_text": True,
            "article": article,
        })

        signature = (
            metadata.get("source_file"),
            metadata.get("page_index"),
            article,
            re.sub(r"\s+", " ", content),
        )
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        cleaned_chunks.append(LangchainDocument(page_content=content, metadata=metadata))

    return cleaned_chunks


def get_embedding_model():
    global _embedding_model

    if _embedding_model is None:
        from langchain_community.embeddings import HuggingFaceEmbeddings

        device = _device()
        print(f"[rag_pipeline] embedding model device={device}")
        _embedding_model = HuggingFaceEmbeddings(
            model_name=os.getenv("RAG_EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask"),
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True},
        )

    return _embedding_model


def get_reranker_model():
    global _reranker_model

    if _reranker_model is None:
        from sentence_transformers import CrossEncoder

        device = _device()
        print(f"[rag_pipeline] reranker device={device}")
        kwargs = {"device": device}
        if device.startswith("cuda"):
            import torch

            # GPU에서는 fp16으로 올려 VRAM 사용량을 낮춘다.
            kwargs["model_kwargs"] = {"torch_dtype": torch.float16}
        _reranker_model = CrossEncoder(
            os.getenv("RAG_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            **kwargs,
        )

    return _reranker_model


def select_pending_documents(documents: List[dict]) -> List[dict]:
    pending = []
    for doc in documents:
        if not doc:
            continue
        if bool(doc.get("is_deleted", False)):
            continue
        if bool(doc.get("is_loaded", False)):
            continue
        pending.append(doc)
    return pending


def select_documents_for_bulk_load(documents: List[dict], *, mode: str = "skip") -> List[dict]:
    selected = []
    for doc in documents:
        if not doc:
            continue
        if bool(doc.get("is_deleted", False)):
            continue
        if bool(doc.get("is_loaded", False)) and mode == "skip":
            continue
        selected.append(doc)
    return selected


def build_vector_store_from_file(file_path: str, output_dir: str, *, doc_id: int, chunk_size: int = 800, chunk_overlap: int = 120):
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_community.vectorstores import FAISS

    loader = PyPDFLoader(file_path)
    pages = loader.load()
    chunks = build_chunks_from_pages(pages, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    if not chunks:
        raise ValueError("No chunks were generated from the uploaded PDF")

    embeddings = get_embedding_model()
    vector_db = FAISS.from_documents(chunks, embeddings)

    os.makedirs(output_dir, exist_ok=True)
    vector_db.save_local(output_dir)
    return len(chunks)


def load_vector_store(vector_path: str, embedding_model):
    from langchain_community.vectorstores import FAISS

    return FAISS.load_local(
        vector_path,
        embedding_model,
        allow_dangerous_deserialization=True,
    )


# 로드된 FAISS 인덱스를 재사용한다. index.faiss의 수정 시각이 바뀌면
# overwrite 재적재로 판단해 다음 검색에서 자동으로 다시 읽는다.
_store_cache: dict = {}


def load_vector_store_cached(vector_path: str, embedding_model):
    index_file = os.path.join(vector_path, "index.faiss")
    try:
        mtime = os.path.getmtime(index_file)
    except OSError:
        mtime = None

    cached = _store_cache.get(vector_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    vector_db = load_vector_store(vector_path, embedding_model)
    _store_cache[vector_path] = (mtime, vector_db)
    return vector_db


def warm_vector_store_cache(vector_root: str, embedding_model) -> tuple[int, list[tuple[str, str]]]:
    """서버 기동 중 문서별 FAISS 인덱스를 미리 읽어 첫 검색 지연을 없앤다.

    깨진 인덱스 하나가 전체 RAG 기동을 막지 않도록 실패 목록을 반환한다. 검색 시에도
    해당 인덱스는 기존과 동일하게 건너뛴다.
    """
    if not os.path.isdir(vector_root):
        return 0, []

    loaded = 0
    failed: list[tuple[str, str]] = []
    for doc_id in sorted(os.listdir(vector_root)):
        vector_path = os.path.join(vector_root, doc_id)
        if not os.path.isdir(vector_path):
            continue

        try:
            load_vector_store_cached(vector_path, embedding_model)
            loaded += 1
        except Exception as exc:
            failed.append((doc_id, str(exc)))

    return loaded, failed


def _select_candidate_pool(
    candidates: List[dict], bm25_scores: List[float], *, limit: int
) -> List[dict]:
    """dense와 lexical 순위를 절반씩 반영한 중복 없는 후보 풀을 만든다."""
    pool_limit = max(0, min(int(limit), len(candidates)))
    if pool_limit == 0:
        return []

    ranked_candidates = []
    max_bm25 = max(bm25_scores) if bm25_scores else 0.0
    for order, (candidate, raw_bm25) in enumerate(zip(candidates, bm25_scores)):
        enriched = dict(candidate)
        enriched["_pool_order"] = order
        enriched["_bm25_raw"] = float(raw_bm25)
        enriched["_bm25_score"] = (
            float(raw_bm25) / float(max_bm25) if max_bm25 > 0 else 0.0
        )
        ranked_candidates.append(enriched)

    dense_ranked = sorted(
        ranked_candidates,
        key=lambda item: (item["score"], item["_pool_order"]),
    )
    # lexical 신호가 전혀 없으면 기존 dense top-N과 같은 후보/순서를 유지한다.
    if max_bm25 <= 0:
        return dense_ranked[:pool_limit]

    lexical_ranked = sorted(
        ranked_candidates,
        key=lambda item: (
            -item["_bm25_raw"],
            item["score"],
            item["_pool_order"],
        ),
    )

    dense_quota = (pool_limit + 1) // 2
    lexical_quota = pool_limit - dense_quota
    selected: List[dict] = []
    selected_orders = set()

    def add(candidate: dict) -> bool:
        identity = candidate["_pool_order"]
        if identity in selected_orders:
            return False
        selected_orders.add(identity)
        selected.append(candidate)
        return True

    for candidate in dense_ranked[:dense_quota]:
        add(candidate)

    lexical_added = 0
    for candidate in lexical_ranked:
        if add(candidate):
            lexical_added += 1
            if lexical_added >= lexical_quota:
                break

    # 전체 후보가 적거나 순위 중복이 많아 quota를 못 채운 경우 dense 우선으로 채운다.
    if len(selected) < pool_limit:
        for candidate in dense_ranked:
            add(candidate)
            if len(selected) >= pool_limit:
                break

    return selected[:pool_limit]


def _reranker_candidate_text(candidate: dict) -> str:
    """CrossEncoder가 출처/조문 범위를 함께 판단하도록 짧은 메타데이터를 붙인다."""
    metadata = dict(candidate.get("metadata", {}) or {})

    def compact(value: Any, *, max_length: int = 80) -> str:
        if isinstance(value, (list, tuple, set)):
            value = ", ".join(str(item) for item in value if item)
        normalized = " ".join(str(value or "").split())
        if len(normalized) <= max_length:
            return normalized
        return normalized[: max_length - 1].rstrip() + "…"

    fields = []
    for label, key in (
        ("source", "source_file"),
        ("title", "document_title"),
        ("authority", "authority"),
        ("audience", "audience"),
        ("article", "article"),
        ("section", "section_type"),
    ):
        value = compact(metadata.get(key))
        if value:
            fields.append(f"{label}={value}")

    content = str(candidate.get("content", ""))
    if not fields:
        return content
    return f"[{'; '.join(fields)}]\n{content}"


def search_across_vector_stores(
    query: str,
    vector_root: str,
    embedding_model,
    reranker_model,
    *,
    top_k: int = 5,
    initial_candidates: int = 20,
):
    query = normalize_search_query(query)
    candidates = []

    # 질문 임베딩을 스토어마다 반복하지 않고 요청당 한 번만 생성한다.
    query_embedding = embedding_model.embed_query(query)

    for doc_id in sorted(os.listdir(vector_root)):
        doc_path = os.path.join(vector_root, doc_id)
        if not os.path.isdir(doc_path):
            continue

        try:
            vector_db = load_vector_store_cached(doc_path, embedding_model)
            docs = vector_db.similarity_search_with_score_by_vector(query_embedding, k=3)
        except Exception:
            continue

        for doc, score in docs:
            candidates.append({
                "doc_id": doc_id,
                "content": getattr(doc, "page_content", ""),
                "metadata": getattr(doc, "metadata", {}),
                "score": float(score),
            })

    if not candidates:
        return []

    # 전체 dense 후보에 lexical 점수를 먼저 계산해야 dense top-20 밖의 정확한
    # 용어 일치 청크도 CrossEncoder 단계에서 복구될 수 있다.
    all_candidate_texts = [item["content"] for item in candidates]
    all_bm25_scores = _calculate_bm25_scores(query, all_candidate_texts)
    candidates = _select_candidate_pool(
        candidates,
        all_bm25_scores,
        limit=initial_candidates,
    )
    if not candidates:
        return []

    pairs = [(query, _reranker_candidate_text(item)) for item in candidates]
    rerank_scores = reranker_model.predict(pairs)

    reranked = []
    for index, candidate in enumerate(candidates):
        rerank_score = float(rerank_scores[index])
        bm25_score = float(candidate["_bm25_score"])
        hybrid_score = (0.7 * rerank_score) + (0.3 * bm25_score)
        reranked.append((candidate, rerank_score, bm25_score, hybrid_score))

    reranked = sorted(reranked, key=lambda item: item[3], reverse=True)

    results = []
    for candidate, rerank_score, bm25_score, hybrid_score in reranked[:top_k]:
        metadata = dict(candidate.get("metadata", {}) or {})
        metadata.setdefault("doc_id", candidate.get("doc_id"))
        metadata.setdefault("source_file", metadata.get("source_file", "unknown.pdf"))
        results.append({
            "doc_id": candidate["doc_id"],
            "content": candidate["content"],
            "metadata": metadata,
            "score": round(float(hybrid_score), 4),
            "rerank_score": round(float(rerank_score), 4),
            "bm25_score": round(float(bm25_score), 4),
            "faiss_score": round(float(candidate["score"]), 4),
        })

    return results
