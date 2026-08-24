import math
import os
import re
from typing import List, Optional, Any


_embedding_model = None
_reranker_model = None


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

    cleaned_chunks: List[Any] = []
    seen_signatures = set()

    for idx, chunk in enumerate(chunks):
        content = _normalize_whitespace(getattr(chunk, "page_content", "") or "")
        if not _is_meaningful_chunk(content, min_length=80):
            continue

        metadata = dict(getattr(chunk, "metadata", {}) or {})
        metadata.update({
            "chunk_id": idx,
            "char_count": len(content),
            "section_heading": content.splitlines()[0][:80] if content.splitlines() else content[:80],
            "source_file": metadata.get("source_file", "unknown.pdf"),
            "page_number": metadata.get("page_number", metadata.get("page", 1)),
            "is_legal_text": True,
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

        _embedding_model = HuggingFaceEmbeddings(
            model_name="jhgan/ko-sroberta-multitask",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

    return _embedding_model


def get_reranker_model():
    global _reranker_model

    if _reranker_model is None:
        from sentence_transformers import CrossEncoder

        _reranker_model = CrossEncoder("BAAI/bge-reranker-v2-m3")

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

    for doc_id in sorted(os.listdir(vector_root)):
        doc_path = os.path.join(vector_root, doc_id)
        if not os.path.isdir(doc_path):
            continue

        try:
            vector_db = load_vector_store(doc_path, embedding_model)
            docs = vector_db.similarity_search_with_score(query, k=3)
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
