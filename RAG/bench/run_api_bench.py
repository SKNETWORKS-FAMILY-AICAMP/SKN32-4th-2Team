"""Benchmark the live RAG ``/api/search`` endpoint without calling an LLM.

The default question set is shared with ``LLM/bench/questions.yaml`` so that
retrieval latency and source-document hit rates can later be compared with the
end-to-end LLM benchmark.  The benchmark is intentionally sequential: this is
the latency seen by one interactive user, not a throughput/load test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


BENCH_DIR = Path(__file__).resolve().parent
RAG_DIR = BENCH_DIR.parent
REPO_DIR = RAG_DIR.parent
DEFAULT_QUESTIONS = REPO_DIR / "LLM" / "bench" / "questions.yaml"
DEFAULT_RESULTS_DIR = BENCH_DIR / "results"


def _percentile(values: list[float], percentile: float) -> float:
    """Return a nearest-rank percentile, suitable for small benchmark samples."""
    if not values:
        raise ValueError("at least one value is required")
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100) * len(ordered)))
    return ordered[rank - 1]


def latency_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "samples": 0,
            "min_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "max_ms": None,
            "mean_ms": None,
        }
    return {
        "samples": len(values),
        "min_ms": round(min(values), 1),
        "p50_ms": round(statistics.median(values), 1),
        "p95_ms": round(_percentile(values, 95), 1),
        "max_ms": round(max(values), 1),
        "mean_ms": round(statistics.mean(values), 1),
    }


def load_questions(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = path.read_bytes()
    payload = yaml.safe_load(raw.decode("utf-8"))
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"No questions found in {path}")

    normalized = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            raise ValueError(f"Question #{index} must be an object")
        question_id = str(question.get("id") or "").strip()
        text = " ".join(str(question.get("question") or "").split())
        if not question_id or not text:
            raise ValueError(f"Question #{index} is missing id or question")
        normalized.append(
            {
                "id": question_id,
                "question": text,
                "category": question.get("category"),
                "group": question.get("group"),
                "expected_sources": list(question.get("sources") or []),
                "out_of_scope": bool(question.get("out_of_scope")),
            }
        )
    return normalized, hashlib.sha256(raw).hexdigest()


def _request_json(
    url: str,
    *,
    timeout: float,
    payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], float, int]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.load(response)
            status = response.status
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        raise RuntimeError(f"request failed after {elapsed_ms:.1f} ms: {exc}") from exc

    elapsed_ms = (time.perf_counter() - started) * 1000
    if not isinstance(parsed, dict):
        raise RuntimeError(f"expected a JSON object from {url}")
    return parsed, elapsed_ms, status


def _compact_results(results: Any) -> list[dict[str, Any]]:
    if not isinstance(results, list):
        return []
    compact = []
    for rank, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") or {}
        content = " ".join(str(item.get("content") or "").split())
        compact.append(
            {
                "rank": rank,
                "doc_id": item.get("doc_id"),
                "source_file": metadata.get("source_file"),
                "page": metadata.get("page_number", metadata.get("page")),
                "article": metadata.get("article"),
                "score": item.get("score"),
                "rerank_score": item.get("rerank_score"),
                "bm25_score": item.get("bm25_score"),
                "faiss_score": item.get("faiss_score"),
                "content_head": content[:120],
            }
        )
    return compact


def source_hit_metrics(
    expected_sources: list[str], results: list[dict[str, Any]]
) -> dict[str, Any]:
    expected = set(expected_sources)
    hit_rank = next(
        (
            result["rank"]
            for result in results
            if result.get("source_file") in expected
        ),
        None,
    )
    return {
        "hit_rank": hit_rank,
        "hit_at_1": bool(hit_rank is not None and hit_rank <= 1),
        "hit_at_3": bool(hit_rank is not None and hit_rank <= 3),
        "hit_at_5": bool(hit_rank is not None and hit_rank <= 5),
        "reciprocal_rank": round(1 / hit_rank, 4) if hit_rank else 0.0,
    }


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
    torch_data: dict[str, Any] = {}
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        torch_data = {
            "torch": torch.__version__,
            "torch_cuda_build": torch.version.cuda,
            "cuda_available": cuda_available,
            "cuda_device": torch.cuda.get_device_name(0) if cuda_available else None,
        }
    except ImportError:
        torch_data = {"torch": None, "cuda_available": False}

    vector_root = RAG_DIR / "vector_store"
    vector_stores = (
        sum(1 for item in vector_root.iterdir() if item.is_dir())
        if vector_root.is_dir()
        else 0
    )
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "vector_store_count": vector_stores,
        **torch_data,
    }


def _ranking_signature(results: list[dict[str, Any]]) -> str:
    ranking = [
        [item.get("doc_id"), item.get("source_file"), item.get("page")]
        for item in results
    ]
    encoded = json.dumps(ranking, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def _quality_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [
        record
        for record in records
        if record["expected_sources"] and not record["out_of_scope"]
    ]
    successful = [record for record in eligible if record["quality"] is not None]
    if not successful:
        return {
            "eligible_questions": len(eligible),
            "scored_questions": 0,
            "source_hit_at_1": None,
            "source_hit_at_3": None,
            "source_hit_at_5": None,
            "mean_reciprocal_rank": None,
        }

    def ratio(key: str) -> float:
        return round(sum(bool(item["quality"][key]) for item in successful) / len(successful), 4)

    return {
        "eligible_questions": len(eligible),
        "scored_questions": len(successful),
        "source_hit_at_1": ratio("hit_at_1"),
        "source_hit_at_3": ratio("hit_at_3"),
        "source_hit_at_5": ratio("hit_at_5"),
        "mean_reciprocal_rank": round(
            statistics.mean(item["quality"]["reciprocal_rank"] for item in successful),
            4,
        ),
    }


def _safe_label(value: str) -> str:
    label = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip()).strip("-.")
    return label or "run"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0, help="0 runs all questions")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--sleep-ms", type=float, default=0.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.warmups < 0 or args.limit < 0 or args.sleep_ms < 0:
        parser.error("--warmups, --limit and --sleep-ms cannot be negative")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def main() -> int:
    args = _parse_args()
    questions, question_sha256 = load_questions(args.questions.resolve())
    if args.limit:
        questions = questions[: args.limit]

    base_url = args.base_url.rstrip("/")
    health_url = f"{base_url}/health"
    search_url = f"{base_url}/api/search"
    try:
        health, health_ms, _ = _request_json(health_url, timeout=args.timeout)
    except RuntimeError as exc:
        print(f"RAG health check failed: {exc}", file=sys.stderr)
        return 2
    if health.get("status") != "ok" or not health.get("models_ready"):
        print(f"RAG is not ready: {health}", file=sys.stderr)
        return 2

    print(
        f"RAG ready: stores={health.get('warmed_vector_stores')} "
        f"warm={health.get('vector_store_cache_warmed')} ({health_ms:.1f} ms)",
        flush=True,
    )
    print(
        f"questions={len(questions)} repeats={args.repeats} "
        f"requests={len(questions) * args.repeats}",
        flush=True,
    )

    for index in range(args.warmups):
        try:
            _, elapsed_ms, _ = _request_json(
                search_url,
                timeout=args.timeout,
                payload={"query": questions[0]["question"]},
            )
        except RuntimeError as exc:
            print(f"Warmup #{index + 1} failed: {exc}", file=sys.stderr)
            return 2
        print(f"warmup {index + 1}/{args.warmups}: {elapsed_ms:.1f} ms", flush=True)

    started_at = datetime.now().astimezone()
    records_by_id: dict[str, dict[str, Any]] = {
        question["id"]: {
            **question,
            "latencies_ms": [],
            "errors": [],
            "ranking_signatures": [],
            "results": [],
            "quality": None,
        }
        for question in questions
    }
    all_latencies: list[float] = []
    total_requests = len(questions) * args.repeats
    request_number = 0

    # Iterate by round so slowdowns caused by time or thermal throttling are not
    # assigned only to the questions at the end of the suite.
    for repeat in range(args.repeats):
        for question in questions:
            request_number += 1
            record = records_by_id[question["id"]]
            try:
                response, elapsed_ms, _ = _request_json(
                    search_url,
                    timeout=args.timeout,
                    payload={"query": question["question"]},
                )
                compact = _compact_results(response.get("results"))
                rounded_ms = round(elapsed_ms, 1)
                record["latencies_ms"].append(rounded_ms)
                record["ranking_signatures"].append(_ranking_signature(compact))
                record["results"] = compact
                all_latencies.append(elapsed_ms)
                outcome = f"{rounded_ms:.1f} ms, {len(compact)} results"
            except RuntimeError as exc:
                record["errors"].append({"repeat": repeat + 1, "message": str(exc)})
                outcome = f"ERROR {exc}"

            print(
                f"[{request_number:03d}/{total_requests:03d}] "
                f"{question['id']}: {outcome}",
                flush=True,
            )
            if args.sleep_ms:
                time.sleep(args.sleep_ms / 1000)

    records = list(records_by_id.values())
    for record in records:
        record["latency"] = latency_summary(record.pop("latencies_ms"))
        signatures = record.pop("ranking_signatures")
        record["ranking_stable"] = len(set(signatures)) <= 1 if signatures else None
        record["ranking_signatures"] = signatures
        if record["results"] and record["expected_sources"] and not record["out_of_scope"]:
            record["quality"] = source_hit_metrics(
                record["expected_sources"], record["results"]
            )

    ended_at = datetime.now().astimezone()
    summary = {
        "latency": latency_summary(all_latencies),
        "failed_requests": sum(len(record["errors"]) for record in records),
        "unstable_rankings": sum(record["ranking_stable"] is False for record in records),
        "quality": _quality_summary(records),
    }
    report = {
        "schema_version": 1,
        "label": args.label,
        "started_at": started_at.isoformat(timespec="seconds"),
        "ended_at": ended_at.isoformat(timespec="seconds"),
        "duration_seconds": round((ended_at - started_at).total_seconds(), 1),
        "endpoint": search_url,
        "settings": {
            "repeats": args.repeats,
            "warmups": args.warmups,
            "timeout_seconds": args.timeout,
            "sleep_ms": args.sleep_ms,
            "question_count": len(questions),
            "questions_file": str(args.questions.resolve()),
            "questions_sha256": question_sha256,
        },
        "git": _git_metadata(),
        "runtime": _runtime_metadata(),
        "health": health,
        "summary": summary,
        "questions": records,
    }

    if args.output:
        output = args.output.resolve()
    else:
        stamp = started_at.strftime("%Y%m%d-%H%M%S")
        output = DEFAULT_RESULTS_DIR / f"{stamp}_{_safe_label(args.label)}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    latency = summary["latency"]
    quality = summary["quality"]
    print("-" * 72)
    print(
        f"latency p50={latency['p50_ms']} ms p95={latency['p95_ms']} ms "
        f"mean={latency['mean_ms']} ms failures={summary['failed_requests']}"
    )
    print(
        f"source hit@1={quality['source_hit_at_1']} "
        f"hit@3={quality['source_hit_at_3']} hit@5={quality['source_hit_at_5']} "
        f"MRR={quality['mean_reciprocal_rank']}"
    )
    print(f"saved: {output}")
    return 1 if summary["failed_requests"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
