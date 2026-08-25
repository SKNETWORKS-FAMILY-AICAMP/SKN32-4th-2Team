r"""Direct RAG backend benchmark with no HTTP server or LLM API calls.

Each command launches a fresh worker process so model/store caches never leak
between backend or device runs.  The corpus is never re-embedded: unified
FAISS and in-memory Qdrant are populated by reconstructing the vectors already
stored under ``RAG/vector_store``.

Examples::

    RAG\.venv\Scripts\python.exe RAG\bench\run_backend_bench.py \
        --backend faiss-cached --device cpu
    RAG\.venv\Scripts\python.exe RAG\bench\run_backend_bench.py \
        --backend qdrant-tuned --device cuda --repeats 3
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


BENCH_DIR = Path(__file__).resolve().parent
RAG_DIR = BENCH_DIR.parent
REPO_DIR = RAG_DIR.parent
DEFAULT_QUESTIONS = REPO_DIR / "LLM" / "bench" / "questions.yaml"
DEFAULT_VECTOR_ROOT = RAG_DIR / "vector_store"
DEFAULT_RESULTS_DIR = BENCH_DIR / "results"

BACKENDS = ("faiss-cached", "faiss-unified", "qdrant-naive", "qdrant-tuned")
DEVICES = ("cpu", "cuda")
TOP_K = 5
INITIAL_CANDIDATES = 20
PER_DOCUMENT = 3
QDRANT_FETCH = 80
TRANSFER_BATCH_SIZE = 256


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("at least one value is required")
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return float(ordered[rank - 1])


def latency_summary(values: Sequence[float]) -> dict[str, float | int | None]:
    """Summarize millisecond samples using a small-sample-safe percentile."""
    if not values:
        return {
            "samples": 0,
            "min_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "max_ms": None,
            "mean_ms": None,
        }
    numeric = [float(value) for value in values]
    return {
        "samples": len(numeric),
        "min_ms": round(min(numeric), 3),
        "p50_ms": round(statistics.median(numeric), 3),
        "p95_ms": round(_percentile(numeric, 95), 3),
        "max_ms": round(max(numeric), 3),
        "mean_ms": round(statistics.mean(numeric), 3),
    }


def euclid_to_squared_l2(distance: float) -> float:
    """Convert Qdrant EUCLID output to FAISS IndexFlatL2's squared distance."""
    numeric = float(distance)
    return numeric * numeric


def apply_per_document_limit(
    candidates: Iterable[dict[str, Any]],
    *,
    per_document: int = PER_DOCUMENT,
    limit: int = INITIAL_CANDIDATES,
) -> list[dict[str, Any]]:
    """Keep distance order while limiting how many chunks one document owns."""
    if per_document < 1 or limit < 0:
        raise ValueError("per_document must be positive and limit cannot be negative")
    selected: list[dict[str, Any]] = []
    counts: dict[Any, int] = {}
    for candidate in candidates:
        doc_id = candidate.get("doc_id")
        if counts.get(doc_id, 0) >= per_document:
            continue
        counts[doc_id] = counts.get(doc_id, 0) + 1
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def source_hit_metrics(
    expected_sources: Sequence[str], results: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    expected = set(expected_sources)
    hit_rank = next(
        (
            rank
            for rank, result in enumerate(results, start=1)
            if result.get("source_file") in expected
        ),
        None,
    )
    return {
        "hit_rank": hit_rank,
        "hit_at_1": bool(hit_rank is not None and hit_rank <= 1),
        "hit_at_3": bool(hit_rank is not None and hit_rank <= 3),
        "hit_at_5": bool(hit_rank is not None and hit_rank <= 5),
        "reciprocal_rank": round(1.0 / hit_rank, 6) if hit_rank else 0.0,
    }


def quality_summary(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one quality result per eligible question."""
    eligible = [
        record
        for record in records
        if record.get("expected_sources") and not record.get("out_of_scope")
    ]
    scored = [record for record in eligible if record.get("quality") is not None]
    if not scored:
        return {
            "eligible_questions": len(eligible),
            "scored_questions": 0,
            "source_hit_at_1": None,
            "source_hit_at_3": None,
            "source_hit_at_5": None,
            "mean_reciprocal_rank": None,
        }

    def ratio(key: str) -> float:
        return round(
            sum(bool(record["quality"][key]) for record in scored) / len(scored),
            6,
        )

    return {
        "eligible_questions": len(eligible),
        "scored_questions": len(scored),
        "source_hit_at_1": ratio("hit_at_1"),
        "source_hit_at_3": ratio("hit_at_3"),
        "source_hit_at_5": ratio("hit_at_5"),
        "mean_reciprocal_rank": round(
            statistics.mean(record["quality"]["reciprocal_rank"] for record in scored),
            6,
        ),
    }


def load_questions(path: Path) -> tuple[list[dict[str, Any]], str]:
    # Kept lazy so utility unit tests do not need the benchmark environment.
    import yaml

    raw = path.read_bytes()
    payload = yaml.safe_load(raw.decode("utf-8"))
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"No questions found in {path}")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Question #{index} must be an object")
        question_id = str(item.get("id") or "").strip()
        question = " ".join(str(item.get("question") or "").split())
        if not question_id or not question:
            raise ValueError(f"Question #{index} is missing id or question")
        if question_id in seen_ids:
            raise ValueError(f"Duplicate question id: {question_id}")
        seen_ids.add(question_id)
        normalized.append(
            {
                "id": question_id,
                "question": question,
                "category": item.get("category"),
                "group": item.get("group"),
                "expected_sources": list(item.get("sources") or []),
                "out_of_scope": bool(item.get("out_of_scope")),
            }
        )
    return normalized, hashlib.sha256(raw).hexdigest()


def _safe_label(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-.") or "run"


def _git_metadata() -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=REPO_DIR,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return completed.stdout.strip()

    status = run("status", "--porcelain")
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(status) if status is not None else None,
    }


def _package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except (ImportError, OSError):
        return None


def _runtime_metadata(torch: Any, device: str) -> dict[str, Any]:
    cuda_available = bool(torch.cuda.is_available())
    return {
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "pid": os.getpid(),
        "device_requested": device,
        "torch": str(torch.__version__),
        "torch_cuda_build": torch.version.cuda,
        "cuda_available": cuda_available,
        "cuda_device": torch.cuda.get_device_name(0) if cuda_available else None,
        "packages": {
            "faiss-cpu": _package_version("faiss-cpu"),
            "sentence-transformers": _package_version("sentence-transformers"),
            "qdrant-client": _package_version("qdrant-client"),
            "psutil": _package_version("psutil"),
        },
    }


def _sync_cuda(torch: Any, device: str) -> None:
    if device == "cuda":
        torch.cuda.synchronize()


def _measure(
    function: Callable[[], Any], *, torch: Any, device: str
) -> tuple[Any, float]:
    # CUDA kernels are asynchronous; synchronize both boundaries so every stage
    # records actual device work instead of only CPU enqueue time.
    _sync_cuda(torch, device)
    started = time.perf_counter()
    result = function()
    _sync_cuda(torch, device)
    return result, (time.perf_counter() - started) * 1000.0


def _vector_store_paths(vector_root: Path) -> list[Path]:
    if not vector_root.is_dir():
        raise FileNotFoundError(f"Vector store root does not exist: {vector_root}")
    paths = sorted(item for item in vector_root.iterdir() if item.is_dir())
    if not paths:
        raise RuntimeError(f"No FAISS stores found under {vector_root}")
    return paths


def _document_from_store(store: Any, position: int) -> Any:
    docstore_id = store.index_to_docstore_id[position]
    document = store.docstore.search(docstore_id)
    if isinstance(document, str):
        raise RuntimeError(f"FAISS docstore lookup failed: {document}")
    return document


def _candidate(
    *,
    doc_id: Any,
    document: Any,
    raw_distance: float,
    raw_metric: str,
) -> dict[str, Any]:
    metadata = dict(getattr(document, "metadata", {}) or {})
    metadata.setdefault("doc_id", str(doc_id))
    metadata.setdefault("source_file", metadata.get("source_file", "unknown.pdf"))
    squared_l2 = (
        euclid_to_squared_l2(raw_distance)
        if raw_metric == "euclid"
        else float(raw_distance)
    )
    return {
        "doc_id": str(doc_id),
        "content": getattr(document, "page_content", "") or "",
        "metadata": metadata,
        "vector_backend_metric": raw_metric,
        "vector_backend_score": float(raw_distance),
        "squared_l2": squared_l2,
    }


class FaissCachedBackend:
    """Production-like document-per-store FAISS search with warmed stores."""

    def __init__(
        self,
        paths: Sequence[Path],
        embedding_model: Any,
        pipeline: Any,
        *,
        initial_candidates: int,
    ):
        self.initial_candidates = initial_candidates
        self.stores: list[tuple[str, Any]] = []
        self.point_count = 0
        for path in paths:
            store = pipeline.load_vector_store_cached(str(path), embedding_model)
            self.stores.append((path.name, store))
            self.point_count += int(store.index.ntotal)

    def search(self, query_vector: Sequence[float]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for doc_id, store in self.stores:
            for document, score in store.similarity_search_with_score_by_vector(
                query_vector, k=PER_DOCUMENT
            ):
                candidates.append(
                    _candidate(
                        doc_id=doc_id,
                        document=document,
                        raw_distance=float(score),
                        raw_metric="squared_l2",
                    )
                )
        return sorted(candidates, key=lambda item: item["squared_l2"])[
            :self.initial_candidates
        ]

    def close(self) -> None:
        return None


class FaissUnifiedBackend:
    """One exact FAISS IndexFlatL2 assembled from existing stored vectors."""

    def __init__(
        self,
        paths: Sequence[Path],
        embedding_model: Any,
        pipeline: Any,
        *,
        initial_candidates: int,
    ):
        import faiss
        import numpy as np

        self._np = np
        self.initial_candidates = initial_candidates
        self.payloads: list[tuple[str, Any]] = []
        self.index: Any = None
        for path in paths:
            store = pipeline.load_vector_store(str(path), embedding_model)
            dimension = int(store.index.d)
            if self.index is None:
                self.index = faiss.IndexFlatL2(dimension)
            elif int(self.index.d) != dimension:
                raise RuntimeError(
                    f"FAISS dimension mismatch in {path}: {dimension} != {self.index.d}"
                )

            for start in range(0, int(store.index.ntotal), TRANSFER_BATCH_SIZE):
                stop = min(start + TRANSFER_BATCH_SIZE, int(store.index.ntotal))
                vectors = np.empty((stop - start, dimension), dtype="float32")
                for offset, position in enumerate(range(start, stop)):
                    vectors[offset] = store.index.reconstruct(position)
                    self.payloads.append(
                        (path.name, _document_from_store(store, position))
                    )
                self.index.add(vectors)
        if self.index is None:
            raise RuntimeError("No vectors were loaded into unified FAISS")
        self.point_count = int(self.index.ntotal)

    def search(self, query_vector: Sequence[float]) -> list[dict[str, Any]]:
        query = self._np.asarray([query_vector], dtype="float32")
        fetch = min(self.initial_candidates, self.point_count)
        distances, positions = self.index.search(query, fetch)
        candidates: list[dict[str, Any]] = []
        for raw_distance, position in zip(distances[0], positions[0]):
            if int(position) < 0:
                continue
            doc_id, document = self.payloads[int(position)]
            candidates.append(
                _candidate(
                    doc_id=doc_id,
                    document=document,
                    raw_distance=float(raw_distance),
                    raw_metric="squared_l2",
                )
            )
        return candidates

    def close(self) -> None:
        return None


class QdrantBackend:
    """Exact local in-memory Qdrant built by streaming existing FAISS vectors."""

    COLLECTION = "rag_backend_bench"

    def __init__(
        self,
        paths: Sequence[Path],
        embedding_model: Any,
        pipeline: Any,
        *,
        tuned: bool,
        initial_candidates: int,
        qdrant_fetch: int,
    ):
        # Lazy by design: FAISS benchmarks and utility tests work without the
        # optional qdrant-client package.
        try:
            from qdrant_client import QdrantClient, models as qm
        except ImportError as exc:
            raise RuntimeError(
                "qdrant-client is required for qdrant-naive/qdrant-tuned; "
                "install it in the existing RAG environment before this run"
            ) from exc

        self._qm = qm
        self.tuned = tuned
        self.initial_candidates = initial_candidates
        self.qdrant_fetch = qdrant_fetch
        self.client = QdrantClient(location=":memory:")
        self.point_count = 0
        dimension: int | None = None
        pending: list[Any] = []

        def flush() -> None:
            if pending:
                self.client.upsert(self.COLLECTION, points=list(pending), wait=True)
                pending.clear()

        for path in paths:
            store = pipeline.load_vector_store(str(path), embedding_model)
            current_dimension = int(store.index.d)
            if dimension is None:
                dimension = current_dimension
                self.client.create_collection(
                    self.COLLECTION,
                    vectors_config=qm.VectorParams(
                        size=dimension,
                        distance=qm.Distance.EUCLID,
                    ),
                )
            elif dimension != current_dimension:
                raise RuntimeError(
                    f"FAISS dimension mismatch in {path}: {current_dimension} != {dimension}"
                )

            for position in range(int(store.index.ntotal)):
                document = _document_from_store(store, position)
                metadata = dict(getattr(document, "metadata", {}) or {})
                payload = {
                    "doc_id": path.name,
                    "content": getattr(document, "page_content", "") or "",
                    "metadata": json.loads(json.dumps(metadata, ensure_ascii=False, default=str)),
                }
                pending.append(
                    qm.PointStruct(
                        id=self.point_count,
                        vector=store.index.reconstruct(position).tolist(),
                        payload=payload,
                    )
                )
                self.point_count += 1
                if len(pending) >= TRANSFER_BATCH_SIZE:
                    flush()
        flush()
        if dimension is None or not self.point_count:
            raise RuntimeError("No vectors were loaded into Qdrant")

    def search(self, query_vector: Sequence[float]) -> list[dict[str, Any]]:
        params = self._qm.SearchParams(exact=True)
        fetch = self.qdrant_fetch if self.tuned else self.initial_candidates
        if hasattr(self.client, "query_points"):
            hits = self.client.query_points(
                self.COLLECTION,
                query=list(query_vector),
                limit=min(fetch, self.point_count),
                search_params=params,
                with_payload=True,
            ).points
        else:  # qdrant-client compatibility before query_points was introduced
            hits = self.client.search(
                self.COLLECTION,
                query_vector=list(query_vector),
                limit=min(fetch, self.point_count),
                search_params=params,
                with_payload=True,
            )

        candidates: list[dict[str, Any]] = []
        for hit in hits:
            payload = hit.payload or {}
            metadata = dict(payload.get("metadata") or {})
            document = _PayloadDocument(payload.get("content", ""), metadata)
            candidates.append(
                _candidate(
                    doc_id=payload.get("doc_id"),
                    document=document,
                    raw_distance=float(hit.score),
                    raw_metric="euclid",
                )
            )
        if self.tuned:
            return apply_per_document_limit(
                candidates,
                per_document=PER_DOCUMENT,
                limit=self.initial_candidates,
            )
        return candidates[: self.initial_candidates]

    def close(self) -> None:
        self.client.close()


class _PayloadDocument:
    def __init__(self, page_content: str, metadata: dict[str, Any]):
        self.page_content = page_content
        self.metadata = metadata


def _build_backend(
    name: str,
    paths: Sequence[Path],
    embedding_model: Any,
    pipeline: Any,
    *,
    initial_candidates: int,
    qdrant_fetch: int,
) -> Any:
    if name == "faiss-cached":
        return FaissCachedBackend(
            paths,
            embedding_model,
            pipeline,
            initial_candidates=initial_candidates,
        )
    if name == "faiss-unified":
        return FaissUnifiedBackend(
            paths,
            embedding_model,
            pipeline,
            initial_candidates=initial_candidates,
        )
    if name == "qdrant-naive":
        return QdrantBackend(
            paths,
            embedding_model,
            pipeline,
            tuned=False,
            initial_candidates=initial_candidates,
            qdrant_fetch=qdrant_fetch,
        )
    if name == "qdrant-tuned":
        return QdrantBackend(
            paths,
            embedding_model,
            pipeline,
            tuned=True,
            initial_candidates=initial_candidates,
            qdrant_fetch=qdrant_fetch,
        )
    raise ValueError(f"Unknown backend: {name}")


def _compact_vector_candidate(candidate: dict[str, Any], rank: int) -> dict[str, Any]:
    metadata = candidate.get("metadata") or {}
    content = " ".join(str(candidate.get("content") or "").split())
    return {
        "rank": rank,
        "doc_id": candidate.get("doc_id"),
        "source_file": metadata.get("source_file"),
        "page": metadata.get("page_number", metadata.get("page")),
        "article": metadata.get("article"),
        "vector_backend_metric": candidate.get("vector_backend_metric"),
        "vector_backend_score": round(float(candidate["vector_backend_score"]), 8),
        "squared_l2": round(float(candidate["squared_l2"]), 8),
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
        "content_head": content[:160],
    }


def _ranking_signature(ranking: Sequence[dict[str, Any]]) -> str:
    identity = [
        [
            item.get("doc_id"),
            item.get("source_file"),
            item.get("page"),
            item.get("content_sha256"),
        ]
        for item in ranking
    ]
    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _search_once(
    query: str,
    *,
    backend: Any,
    embedding_model: Any,
    reranker_model: Any,
    pipeline: Any,
    torch: Any,
    device: str,
) -> dict[str, Any]:
    _sync_cuda(torch, device)
    total_started = time.perf_counter()

    query_vector, embed_ms = _measure(
        lambda: embedding_model.embed_query(query), torch=torch, device=device
    )
    candidates, vector_ms = _measure(
        lambda: backend.search(query_vector), torch=torch, device=device
    )

    texts = [candidate["content"] for candidate in candidates]
    def calculate_bm25() -> list[float]:
        raw_scores = pipeline._calculate_bm25_scores(query, texts)
        maximum = max(raw_scores) if raw_scores else 0.0
        return (
            [float(score) / maximum for score in raw_scores]
            if maximum > 0
            else [0.0 for _ in raw_scores]
        )

    normalized_bm25, bm25_ms = _measure(
        calculate_bm25, torch=torch, device=device
    )

    pairs = [(query, candidate["content"]) for candidate in candidates]
    rerank_scores, rerank_ms = _measure(
        lambda: reranker_model.predict(pairs) if pairs else [],
        torch=torch,
        device=device,
    )

    def finalize() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        vector_ranking = [
            _compact_vector_candidate(candidate, rank)
            for rank, candidate in enumerate(candidates, start=1)
        ]
        rescored: list[tuple[float, dict[str, Any]]] = []
        for index, candidate in enumerate(candidates):
            rerank_score = float(rerank_scores[index])
            bm25_score = float(normalized_bm25[index])
            hybrid_score = (0.7 * rerank_score) + (0.3 * bm25_score)
            compact = _compact_vector_candidate(candidate, 0)
            compact.update(
                {
                    "hybrid_score": round(hybrid_score, 8),
                    "rerank_score": round(rerank_score, 8),
                    "bm25_score": round(bm25_score, 8),
                }
            )
            rescored.append((hybrid_score, compact))
        rescored.sort(key=lambda item: item[0], reverse=True)
        final_ranking: list[dict[str, Any]] = []
        for rank, (_, compact) in enumerate(rescored[:TOP_K], start=1):
            compact["rank"] = rank
            final_ranking.append(compact)
        return vector_ranking, final_ranking

    (vector_ranking, final_ranking), finalize_ms = _measure(
        finalize, torch=torch, device=device
    )
    _sync_cuda(torch, device)
    total_ms = (time.perf_counter() - total_started) * 1000.0
    return {
        "timings_ms": {
            "embed": round(embed_ms, 3),
            "vector_search": round(vector_ms, 3),
            "bm25": round(bm25_ms, 3),
            "rerank": round(rerank_ms, 3),
            "finalize": round(finalize_ms, 3),
            "total": round(total_ms, 3),
        },
        "vector_ranking": vector_ranking,
        "vector_ranking_signature": _ranking_signature(vector_ranking),
        "final_ranking": final_ranking,
        "final_ranking_signature": _ranking_signature(final_ranking),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--device", choices=DEVICES, required=True)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--vector-root", type=Path, default=DEFAULT_VECTOR_ROOT)
    parser.add_argument("--label", default="current")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--initial-candidates",
        type=int,
        default=INITIAL_CANDIDATES,
        help="Number of chunks sent to BM25/CrossEncoder (compare 10 vs 20)",
    )
    parser.add_argument(
        "--qdrant-fetch",
        type=int,
        default=QDRANT_FETCH,
        help="Exact Qdrant hits fetched before tuned per-document limiting",
    )
    parser.add_argument("--limit", type=int, default=0, help="0 runs all questions")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.warmups < 0 or args.limit < 0:
        parser.error("--warmups and --limit cannot be negative")
    if args.initial_candidates < TOP_K:
        parser.error(f"--initial-candidates must be at least top-k ({TOP_K})")
    if args.qdrant_fetch < args.initial_candidates:
        parser.error("--qdrant-fetch cannot be smaller than --initial-candidates")
    return args


def _launch_fresh_worker() -> int:
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--_worker"]
    try:
        return subprocess.run(command, check=False).returncode
    except KeyboardInterrupt:
        return 130


def _run_worker(args: argparse.Namespace) -> int:
    # Set before importing rag_pipeline/model libraries.
    os.environ["RAG_DEVICE"] = args.device
    sys.path.insert(0, str(RAG_DIR))

    started_at = datetime.now().astimezone()
    rss_start = _rss_bytes()
    try:
        import torch
    except ImportError as exc:
        print(f"PyTorch is required: {exc}", file=sys.stderr)
        return 2
    if args.device == "cuda" and not torch.cuda.is_available():
        print(
            "CUDA was requested but this RAG environment has no CUDA-capable "
            "PyTorch/device. Use --device cpu or install a compatible CUDA "
            "PyTorch build in the existing RAG environment.",
            file=sys.stderr,
        )
        return 2

    try:
        import rag_pipeline as pipeline

        questions, questions_sha256 = load_questions(args.questions.resolve())
        if args.limit:
            questions = questions[: args.limit]
        paths = _vector_store_paths(args.vector_root.resolve())

        embedding_model, embedding_model_ms = _measure(
            pipeline.get_embedding_model, torch=torch, device=args.device
        )
        reranker_model, reranker_model_ms = _measure(
            pipeline.get_reranker_model, torch=torch, device=args.device
        )
        backend, backend_init_ms = _measure(
            lambda: _build_backend(
                args.backend,
                paths,
                embedding_model,
                pipeline,
                initial_candidates=args.initial_candidates,
                qdrant_fetch=args.qdrant_fetch,
            ),
            torch=torch,
            device=args.device,
        )
    except Exception as exc:
        print(f"Benchmark initialization failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    rss_after_init = _rss_bytes()
    print(
        f"backend={args.backend} device={args.device} stores={len(paths)} "
        f"points={backend.point_count} questions={len(questions)}",
        flush=True,
    )

    try:
        for warmup in range(args.warmups):
            result = _search_once(
                questions[warmup % len(questions)]["question"],
                backend=backend,
                embedding_model=embedding_model,
                reranker_model=reranker_model,
                pipeline=pipeline,
                torch=torch,
                device=args.device,
            )
            print(
                f"warmup {warmup + 1}/{args.warmups}: "
                f"{result['timings_ms']['total']:.1f} ms",
                flush=True,
            )

        records: list[dict[str, Any]] = [
            {**question, "runs": [], "quality": None}
            for question in questions
        ]
        total_runs = len(records) * args.repeats
        run_number = 0
        # Round-major order reduces time/thermal bias between questions.
        for repeat in range(1, args.repeats + 1):
            for record in records:
                run_number += 1
                result = _search_once(
                    record["question"],
                    backend=backend,
                    embedding_model=embedding_model,
                    reranker_model=reranker_model,
                    pipeline=pipeline,
                    torch=torch,
                    device=args.device,
                )
                result["repeat"] = repeat
                record["runs"].append(result)
                print(
                    f"[{run_number:03d}/{total_runs:03d}] {record['id']}: "
                    f"{result['timings_ms']['total']:.1f} ms",
                    flush=True,
                )

        stage_names = ("embed", "vector_search", "bm25", "rerank", "finalize", "total")
        stage_values = {
            stage: [
                run["timings_ms"][stage]
                for record in records
                for run in record["runs"]
            ]
            for stage in stage_names
        }
        for record in records:
            record["latency"] = latency_summary(
                [run["timings_ms"]["total"] for run in record["runs"]]
            )
            signatures = [run["final_ranking_signature"] for run in record["runs"]]
            record["ranking_stable"] = len(set(signatures)) <= 1
            if record["expected_sources"] and not record["out_of_scope"]:
                record["quality"] = source_hit_metrics(
                    record["expected_sources"], record["runs"][0]["final_ranking"]
                )

        ended_at = datetime.now().astimezone()
        report = {
            "schema_version": 1,
            "benchmark": "rag-backend-direct",
            "label": args.label,
            "started_at": started_at.isoformat(timespec="seconds"),
            "ended_at": ended_at.isoformat(timespec="seconds"),
            "duration_seconds": round((ended_at - started_at).total_seconds(), 3),
            "settings": {
                "backend": args.backend,
                "device": args.device,
                "repeats": args.repeats,
                "warmups": args.warmups,
                "question_count": len(records),
                "questions_file": str(args.questions.resolve()),
                "questions_sha256": questions_sha256,
                "vector_root": str(args.vector_root.resolve()),
                "top_k": TOP_K,
                "initial_candidates": args.initial_candidates,
                "per_document": PER_DOCUMENT,
                "qdrant_fetch": args.qdrant_fetch,
                "qdrant_exact": args.backend.startswith("qdrant"),
                "qdrant_document_diversity": args.backend == "qdrant-tuned",
                "corpus_reembedded": False,
                "fresh_worker_process": True,
            },
            "git": _git_metadata(),
            "runtime": _runtime_metadata(torch, args.device),
            "memory": {
                "rss_bytes_at_start": rss_start,
                "rss_bytes_after_init": rss_after_init,
                "rss_bytes_at_end": _rss_bytes(),
            },
            "corpus": {
                "vector_store_count": len(paths),
                "point_count": int(backend.point_count),
            },
            "initialization_ms": {
                "embedding_model": round(embedding_model_ms, 3),
                "reranker_model": round(reranker_model_ms, 3),
                "models_total": round(embedding_model_ms + reranker_model_ms, 3),
                "store_or_backend_build": round(backend_init_ms, 3),
                "store": (
                    round(backend_init_ms, 3)
                    if args.backend.startswith("faiss")
                    else None
                ),
                "qdrant_build": (
                    round(backend_init_ms, 3)
                    if args.backend.startswith("qdrant")
                    else None
                ),
                "total": round(
                    embedding_model_ms + reranker_model_ms + backend_init_ms, 3
                ),
            },
            "summary": {
                "stages_ms": {
                    stage: latency_summary(values)
                    for stage, values in stage_values.items()
                },
                "quality": quality_summary(records),
                "unstable_rankings": sum(
                    record["ranking_stable"] is False for record in records
                ),
            },
            "questions": records,
        }

        if args.output:
            output = args.output.resolve()
        else:
            stamp = started_at.strftime("%Y%m%d-%H%M%S")
            filename = (
                f"{stamp}_{_safe_label(args.label)}_"
                f"{args.backend}-{args.device}.json"
            )
            output = DEFAULT_RESULTS_DIR / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        total = report["summary"]["stages_ms"]["total"]
        quality = report["summary"]["quality"]
        print("-" * 72)
        print(
            f"total p50={total['p50_ms']} ms p95={total['p95_ms']} ms "
            f"mean={total['mean_ms']} ms"
        )
        print(
            f"source hit@1={quality['source_hit_at_1']} "
            f"hit@3={quality['source_hit_at_3']} "
            f"hit@5={quality['source_hit_at_5']} "
            f"MRR={quality['mean_reciprocal_rank']}"
        )
        print(f"saved: {output}")
        return 0
    except Exception as exc:
        print(f"Benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        backend.close()


def main() -> int:
    args = _parse_args()
    if not args._worker:
        return _launch_fresh_worker()
    return _run_worker(args)


if __name__ == "__main__":
    raise SystemExit(main())
