import math
import os
import re
from typing import List, Optional, Any


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


def _normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"(?i)\bpage\s*\d+\b", "", text)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


# 조문 머리(예: 제60조(연차 유급휴가))를 청크 앞에 보강한다. 조문 중간에서
# 잘린 청크도 LLM이 근거 조문을 식별할 수 있게 하기 위한 메타데이터다.
_ARTICLE_HEAD = re.compile(r"제\s?\d+조(?:의\s?\d+)?\s*\([^)]{1,40}\)")


def _article_heads(text: str) -> List[tuple]:
    """본문에서 (문자 위치, 조문 머리) 목록을 추출한다."""
    return [
        (match.start(), re.sub(r"\s+", " ", match.group(0)).strip())
        for match in _ARTICLE_HEAD.finditer(text)
    ]


def _head_for(offset: int, heads: List[tuple]) -> Optional[str]:
    """지정 위치보다 앞에 있는 가장 가까운 조문 머리를 반환한다."""
    found = None
    for position, head in heads:
        if position <= offset:
            found = head
        else:
            break
    return found


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


def preprocess_pages(pages: List[Any]) -> List[Any]:
    documents = []
    for idx, page in enumerate(pages):
        raw_text = getattr(page, "page_content", "") or ""
        cleaned_text = _normalize_whitespace(raw_text)
        if not cleaned_text:
            continue

        metadata = dict(getattr(page, "metadata", {}) or {})
        metadata.setdefault("page", idx + 1)
        metadata.setdefault("source_file", os.path.basename(str(metadata.get("source", "unknown.pdf"))))
        metadata.setdefault("page_number", int(metadata.get("page", idx + 1)))

        documents.append(LangchainDocument(page_content=cleaned_text, metadata=metadata))

    return documents


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

    if separators is None:
        separators = ["\n제", "\n\n", "\n", " ", ""]

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators,
        )
        chunks = splitter.split_documents(documents)
    except Exception:
        chunks = []
        for doc in documents:
            content = doc.page_content
            parts = re.split(r"\n{2,}", content)
            for part in parts:
                if part.strip():
                    chunks.append(LangchainDocument(page_content=part.strip(), metadata=doc.metadata.copy()))

    # 페이지를 넘어 이어지는 조문도 처리하려고, 페이지별 머리 목록과
    # 이전 페이지에서 이어진 마지막 조문을 먼저 계산한다.
    page_info: dict = {}
    carry_by_source: dict = {}
    for doc in documents:
        source_key = (doc.metadata or {}).get("source_file", "")
        page_text = getattr(doc, "page_content", "") or ""
        # 청크는 공백 정규화를 거치므로 좌표도 공백을 제거한 기준으로 맞춘다.
        heads = [
            (len(re.sub(r"\s+", "", page_text[:position])), head)
            for position, head in _article_heads(page_text)
        ]
        page_info[id(doc)] = (heads, carry_by_source.get(source_key))
        if heads:
            carry_by_source[source_key] = heads[-1][1]

    cleaned_chunks: List[Any] = []
    seen_signatures = set()
    min_chunk_length = int(os.getenv("RAG_MIN_CHUNK_LENGTH", "80"))

    for idx, chunk in enumerate(chunks):
        content = _normalize_whitespace(getattr(chunk, "page_content", "") or "")
        if not _is_meaningful_chunk(content, min_length=min_chunk_length):
            continue

        metadata = dict(getattr(chunk, "metadata", {}) or {})
        source_key = metadata.get("source_file", "")
        article = None
        probe = re.sub(r"\s+", "", content[:40])
        for doc in documents:
            if (doc.metadata or {}).get("source_file") != source_key:
                continue
            flattened_page = re.sub(r"\s+", "", getattr(doc, "page_content", "") or "")
            offset = flattened_page.find(probe)
            if offset < 0:
                continue
            heads, carry_in = page_info[id(doc)]
            article = _head_for(offset, heads) or carry_in
            break

        # 청크의 시작 조문을 확실히 남긴다. 본문 뒤에 다른 조문이 있어도
        # 앞부분의 근거를 그 다른 조문으로 잘못 인용하지 않게 한다.
        if (
            article
            and os.getenv("RAG_ARTICLE_HEAD", "1") != "0"
            and not _ARTICLE_HEAD.match(content)
        ):
            content = f"[{article}] {content}"

        metadata.update({
            "chunk_id": idx,
            "char_count": len(content),
            "section_heading": content.splitlines()[0][:80] if content.splitlines() else content[:80],
            "source_file": metadata.get("source_file", "unknown.pdf"),
            "page_number": metadata.get("page_number", metadata.get("page", 1)),
            "is_legal_text": True,
            "article": article,
        })

        signature = re.sub(r"\s+", " ", content)
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


def search_across_vector_stores(
    query: str,
    vector_root: str,
    embedding_model,
    reranker_model,
    *,
    top_k: int = 5,
    initial_candidates: int = 20,
):
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

    candidates = sorted(candidates, key=lambda item: item["score"])[:initial_candidates]

    candidate_texts = [item["content"] for item in candidates]
    bm25_scores = _calculate_bm25_scores(query, candidate_texts)
    max_bm25 = max(bm25_scores) if bm25_scores else 0.0
    if max_bm25 > 0:
        normalized_bm25 = [score / max_bm25 for score in bm25_scores]
    else:
        normalized_bm25 = [0.0 for _ in bm25_scores]

    pairs = [(query, item["content"]) for item in candidates]
    rerank_scores = reranker_model.predict(pairs)

    reranked = []
    for index, candidate in enumerate(candidates):
        rerank_score = float(rerank_scores[index])
        bm25_score = float(normalized_bm25[index])
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
