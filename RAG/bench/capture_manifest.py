"""Capture a reproducibility manifest for the current RAG benchmark assets.

The manifest deliberately records hashes and metadata, never PDF contents,
pickled document contents, database settings, or a dump of ``RAG/.env``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


BENCH_DIR = Path(__file__).resolve().parent
RAG_DIR = BENCH_DIR.parent
REPO_DIR = RAG_DIR.parent
DEFAULT_PDF_DIR = RAG_DIR / "res" / "pdf"
DEFAULT_VECTOR_DIR = RAG_DIR / "vector_store"
DEFAULT_QUESTIONS = REPO_DIR / "LLM" / "bench" / "questions.yaml"
DEFAULT_RESULTS_DIR = BENCH_DIR / "results"


def sha256_file(path: Path, *, block_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of *path* without loading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_file_records(paths: Iterable[Path], *, root: Path) -> list[dict[str, Any]]:
    """Hash files and return records sorted by deterministic POSIX relative path."""
    root = root.resolve()
    resolved = [Path(path).resolve() for path in paths]
    resolved.sort(key=lambda path: path.relative_to(root).as_posix())
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in resolved
    ]


def aggregate_digest(records: Iterable[dict[str, Any]]) -> str:
    """Hash the canonical path, size, and digest tuples in path order."""
    canonical_records = [
        {
            "path": str(record["path"]),
            "size_bytes": int(record["size_bytes"]),
            "sha256": str(record["sha256"]),
        }
        for record in records
    ]
    canonical_records.sort(key=lambda record: record["path"])
    payload = json.dumps(
        canonical_records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_DIR.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


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


def _runtime_metadata() -> dict[str, Any]:
    torch_metadata: dict[str, Any]
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        devices = []
        if cuda_available:
            for device_index in range(torch.cuda.device_count()):
                properties = torch.cuda.get_device_properties(device_index)
                devices.append(
                    {
                        "index": device_index,
                        "name": torch.cuda.get_device_name(device_index),
                        "compute_capability": list(torch.cuda.get_device_capability(device_index)),
                        "total_memory_bytes": int(properties.total_memory),
                    }
                )
        torch_metadata = {
            "version": str(torch.__version__),
            "cuda_build": str(torch.version.cuda) if torch.version.cuda else None,
            "cuda_available": cuda_available,
            "cudnn_version": torch.backends.cudnn.version() if cuda_available else None,
            "num_threads": int(torch.get_num_threads()),
            "num_interop_threads": int(torch.get_num_interop_threads()),
            "devices": devices,
        }
    except ImportError:
        torch_metadata = {
            "version": None,
            "cuda_build": None,
            "cuda_available": False,
            "cudnn_version": None,
            "num_threads": None,
            "num_interop_threads": None,
            "devices": [],
        }

    return {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "torch": torch_metadata,
    }


def _retrieval_config() -> dict[str, Any]:
    """Load only the non-secret allowlisted retrieval settings."""
    spec = importlib.util.spec_from_file_location("rag_manifest_config", RAG_DIR / "config.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load RAG config from {RAG_DIR / 'config.py'}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = module.Config
    requested_device = os.getenv("RAG_DEVICE", "").strip().lower() or "auto"
    if requested_device == "auto":
        try:
            import torch

            effective_device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            effective_device = "cpu"
    else:
        effective_device = requested_device

    return {
        "chunking": {
            "chunk_size": int(config.CHUNK_SIZE),
            "chunk_overlap": int(config.CHUNK_OVERLAP),
            "min_chunk_length": int(config.MIN_CHUNK_LENGTH),
            "article_head_enabled": os.getenv("RAG_ARTICLE_HEAD", "1") != "0",
        },
        "search": {
            "top_k": int(config.SEARCH_TOP_K),
            "initial_candidates": int(config.SEARCH_INITIAL_CANDIDATES),
        },
        "models": {
            "embedding": str(config.EMBEDDING_MODEL),
            "reranker": str(config.RERANKER_MODEL),
        },
        "execution": {
            "device_requested": requested_device,
            "device_effective": effective_device,
            "warm_vector_stores": bool(config.WARM_VECTOR_STORES),
        },
    }


def _faiss_module() -> Any:
    try:
        import faiss
    except ImportError as exc:
        raise RuntimeError(
            "FAISS is required to record index type, dimension, metric, and chunk count. "
            "Run this command with RAG/.venv; no index.pkl fallback is used."
        ) from exc
    return faiss


def _metric_name(faiss: Any, metric_code: int) -> str | None:
    names = sorted(
        name
        for name in dir(faiss)
        if name.startswith("METRIC_") and getattr(faiss, name) == metric_code
    )
    return names[0] if names else None


def _pdf_manifest() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not DEFAULT_PDF_DIR.is_dir():
        raise FileNotFoundError(f"PDF corpus directory not found: {DEFAULT_PDF_DIR}")
    pdf_paths = [
        path
        for path in DEFAULT_PDF_DIR.iterdir()
        if path.is_file() and path.suffix.lower() == ".pdf"
    ]
    records = collect_file_records(pdf_paths, root=REPO_DIR)
    return (
        {
            "root": _repo_relative(DEFAULT_PDF_DIR),
            "pdf_count": len(records),
            "total_bytes": sum(record["size_bytes"] for record in records),
            "aggregate_sha256": aggregate_digest(records),
            "files": records,
        },
        records,
    )


def _vector_store_manifest() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not DEFAULT_VECTOR_DIR.is_dir():
        raise FileNotFoundError(f"Vector store directory not found: {DEFAULT_VECTOR_DIR}")

    faiss = _faiss_module()
    store_dirs = sorted(
        (path for path in DEFAULT_VECTOR_DIR.iterdir() if path.is_dir()),
        key=lambda path: path.relative_to(REPO_DIR).as_posix(),
    )
    all_file_records: list[dict[str, Any]] = []
    stores: list[dict[str, Any]] = []

    for store_dir in store_dirs:
        required_files = [store_dir / "index.faiss", store_dir / "index.pkl"]
        missing = [path.name for path in required_files if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"Vector store {_repo_relative(store_dir)} is missing: {', '.join(missing)}"
            )

        file_records = collect_file_records(required_files, root=REPO_DIR)
        all_file_records.extend(file_records)
        index_path = store_dir / "index.faiss"
        try:
            index = faiss.read_index(str(index_path))
        except Exception as exc:
            raise RuntimeError(f"Could not read FAISS index: {_repo_relative(index_path)}") from exc

        metric_code = int(index.metric_type)
        stores.append(
            {
                "path": _repo_relative(store_dir),
                "files": file_records,
                "faiss": {
                    "index_type": type(index).__name__,
                    "dimension": int(index.d),
                    "ntotal": int(index.ntotal),
                    "metric": {
                        "code": metric_code,
                        "name": _metric_name(faiss, metric_code),
                    },
                },
            }
        )

    index_types = sorted({store["faiss"]["index_type"] for store in stores})
    dimensions = sorted({store["faiss"]["dimension"] for store in stores})
    metrics_by_pair = {
        (store["faiss"]["metric"]["code"], store["faiss"]["metric"]["name"])
        for store in stores
    }
    metrics = [
        {"code": code, "name": name}
        for code, name in sorted(metrics_by_pair, key=lambda item: (item[0], item[1] or ""))
    ]

    return (
        {
            "root": _repo_relative(DEFAULT_VECTOR_DIR),
            "faiss_version": str(getattr(faiss, "__version__", "unknown")),
            "store_count": len(stores),
            "file_count": len(all_file_records),
            "total_bytes": sum(record["size_bytes"] for record in all_file_records),
            "aggregate_sha256": aggregate_digest(all_file_records),
            "total_chunks": sum(store["faiss"]["ntotal"] for store in stores),
            "index_types": index_types,
            "dimensions": dimensions,
            "metrics": metrics,
            "stores": stores,
        },
        all_file_records,
    )


def build_manifest(*, output_path: Path, argv: list[str]) -> dict[str, Any]:
    if not DEFAULT_QUESTIONS.is_file():
        raise FileNotFoundError(f"Question set not found: {DEFAULT_QUESTIONS}")

    pdf_manifest, pdf_records = _pdf_manifest()
    vector_manifest, vector_records = _vector_store_manifest()
    question_record = collect_file_records([DEFAULT_QUESTIONS], root=REPO_DIR)[0]
    all_asset_records = [*pdf_records, *vector_records, question_record]

    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": {
            "script": _repo_relative(Path(__file__)),
            "argv": argv,
            "output": _repo_relative(output_path),
        },
        "git": _git_metadata(),
        "runtime": _runtime_metadata(),
        "configuration": _retrieval_config(),
        "questions": question_record,
        "corpus": pdf_manifest,
        "vector_stores": vector_manifest,
        "experiment_assets": {
            "file_count": len(all_asset_records),
            "total_bytes": sum(record["size_bytes"] for record in all_asset_records),
            "aggregate_sha256": aggregate_digest(all_asset_records),
        },
    }


def _default_output() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_RESULTS_DIR / f"{timestamp}_manifest.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture hashes and runtime metadata for a reproducible RAG benchmark."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSON output path (default: RAG/bench/results/<UTC>_manifest.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_path = (args.output or _default_output()).resolve()
    command_argv = list(argv) if argv is not None else sys.argv[1:]
    manifest = build_manifest(output_path=output_path, argv=command_argv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"manifest: {output_path}")
    print(
        "assets: "
        f"pdfs={manifest['corpus']['pdf_count']}, "
        f"stores={manifest['vector_stores']['store_count']}, "
        f"chunks={manifest['vector_stores']['total_chunks']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
