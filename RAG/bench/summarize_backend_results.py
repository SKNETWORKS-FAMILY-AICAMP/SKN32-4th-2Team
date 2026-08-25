"""Create a compact, auditable summary of controlled backend benchmarks.

The raw benchmark JSON files intentionally retain every ranking and timing
sample.  This script extracts the comparison matrix used by REPORT.md while
recording each input file's SHA-256 so the table can be traced back to raw
evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _final_rankings(payload: dict[str, Any]) -> dict[str, list[tuple[str, int, str]]]:
    rankings: dict[str, list[tuple[str, int, str]]] = {}
    for question in payload["questions"]:
        runs = question.get("runs", [])
        if not runs:
            raise ValueError(f"question {question['id']!r} has no measured runs")
        run_rankings = [
            [
                (
                    item["source_file"],
                    int(item["page"]),
                    item["content_sha256"],
                )
                for item in run["final_ranking"]
            ]
            for run in runs
        ]
        if any(ranking != run_rankings[0] for ranking in run_rankings[1:]):
            raise ValueError(f"question {question['id']!r} has unstable final rankings")
        rankings[question["id"]] = run_rankings[0]
    return rankings


def _question_quality(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    quality_by_question: dict[str, dict[str, Any]] = {}
    for question in payload["questions"]:
        quality = question.get("quality") or {}
        quality_by_question[question["id"]] = {
            "out_of_scope": question["out_of_scope"],
            "hit_rank": quality.get("hit_rank"),
            "hit_at_1": quality.get("hit_at_1"),
            "hit_at_3": quality.get("hit_at_3"),
            "hit_at_5": quality.get("hit_at_5"),
        }
    return quality_by_question


def _matrix_key(payload: dict[str, Any]) -> tuple[str, str, int]:
    settings = payload["settings"]
    return (
        settings["backend"],
        settings["device"],
        int(settings["initial_candidates"]),
    )


def _load_inputs(paths: Iterable[Path]) -> dict[tuple[str, str, int], dict[str, Any]]:
    loaded: dict[tuple[str, str, int], dict[str, Any]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("benchmark") != "rag-backend-direct":
            raise ValueError(f"{path} is not a direct backend benchmark")
        key = _matrix_key(payload)
        if key in loaded:
            raise ValueError(f"duplicate matrix cell {key}: {path}")
        payload["_source_path"] = path
        payload["_source_sha256"] = _sha256(path)
        loaded[key] = payload
    return loaded


def _validate_invariants(
    loaded: dict[tuple[str, str, int], dict[str, Any]],
) -> dict[str, Any]:
    if not loaded:
        raise ValueError("no benchmark inputs")

    fields = {
        "questions_sha256": lambda p: p["settings"]["questions_sha256"],
        "question_count": lambda p: p["settings"]["question_count"],
        "repeats": lambda p: p["settings"]["repeats"],
        "warmups": lambda p: p["settings"]["warmups"],
        "top_k": lambda p: p["settings"]["top_k"],
        "per_document": lambda p: p["settings"]["per_document"],
        "qdrant_fetch": lambda p: p["settings"]["qdrant_fetch"],
        "vector_store_count": lambda p: p["corpus"]["vector_store_count"],
        "point_count": lambda p: p["corpus"]["point_count"],
        "torch": lambda p: p["runtime"]["torch"],
        "git_commit": lambda p: p["git"]["commit"],
        "git_dirty": lambda p: p["git"]["dirty"],
    }
    invariants: dict[str, Any] = {}
    for name, getter in fields.items():
        values = {json.dumps(getter(payload), ensure_ascii=False) for payload in loaded.values()}
        if len(values) != 1:
            raise ValueError(f"invariant {name!r} differs across runs: {sorted(values)}")
        invariants[name] = getter(next(iter(loaded.values())))

    expected = {
        (backend, device, candidates)
        for backend in ("faiss-cached", "qdrant-tuned")
        for device in ("cpu", "cuda")
        for candidates in (10, 20)
    }
    missing = sorted(expected - set(loaded))
    unexpected = sorted(set(loaded) - expected)
    if missing or unexpected:
        raise ValueError(f"matrix mismatch; missing={missing}, unexpected={unexpected}")
    return invariants


def _manifest_summary(path: Path, invariants: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = payload["questions"]
    stores = payload["vector_stores"]
    corpus = payload["corpus"]
    if questions["sha256"] != invariants["questions_sha256"]:
        raise ValueError("manifest question SHA-256 differs from benchmark inputs")
    if stores["store_count"] != invariants["vector_store_count"]:
        raise ValueError("manifest vector store count differs from benchmark inputs")
    if stores["total_chunks"] != invariants["point_count"]:
        raise ValueError("manifest chunk count differs from benchmark inputs")
    if payload["git"]["commit"] != invariants["git_commit"]:
        raise ValueError("manifest Git commit differs from benchmark inputs")
    if payload["git"]["dirty"] or invariants["git_dirty"]:
        raise ValueError("manifest or benchmark was captured from a dirty worktree")
    return {
        "source_file": _relative(path),
        "source_sha256": _sha256(path),
        "captured_at_utc": payload["created_at_utc"],
        "git": payload["git"],
        "pdf_count": corpus["pdf_count"],
        "pdf_aggregate_sha256": corpus["aggregate_sha256"],
        "vector_store_count": stores["store_count"],
        "chunk_count": stores["total_chunks"],
        "vector_store_aggregate_sha256": stores["aggregate_sha256"],
        "experiment_assets_aggregate_sha256": payload["experiment_assets"][
            "aggregate_sha256"
        ],
        "configuration": payload["configuration"],
        "runtime": payload["runtime"],
    }


def _round(value: float) -> float:
    return round(float(value), 4)


def _matrix_row(payload: dict[str, Any]) -> dict[str, Any]:
    settings = payload["settings"]
    stages = payload["summary"]["stages_ms"]
    quality = payload["summary"]["quality"]
    return {
        "backend": settings["backend"],
        "device": settings["device"],
        "initial_candidates": settings["initial_candidates"],
        "source_file": _relative(payload["_source_path"]),
        "source_sha256": payload["_source_sha256"],
        "git_commit": payload["git"]["commit"],
        "git_dirty": payload["git"]["dirty"],
        "duration_seconds": payload["duration_seconds"],
        "initialization_total_ms": payload["initialization_ms"]["total"],
        "backend_build_ms": payload["initialization_ms"]["store_or_backend_build"],
        "rss_after_init_bytes": payload["memory"]["rss_bytes_after_init"],
        "rss_at_end_bytes": payload["memory"]["rss_bytes_at_end"],
        "total_min_ms": stages["total"]["min_ms"],
        "total_p50_ms": stages["total"]["p50_ms"],
        "total_p95_ms": stages["total"]["p95_ms"],
        "total_max_ms": stages["total"]["max_ms"],
        "total_mean_ms": stages["total"]["mean_ms"],
        "embed_p50_ms": stages["embed"]["p50_ms"],
        "vector_search_p50_ms": stages["vector_search"]["p50_ms"],
        "bm25_p50_ms": stages["bm25"]["p50_ms"],
        "rerank_p50_ms": stages["rerank"]["p50_ms"],
        "finalize_p50_ms": stages["finalize"]["p50_ms"],
        "eligible_questions": quality["eligible_questions"],
        "source_hit_at_1": quality["source_hit_at_1"],
        "source_hit_at_3": quality["source_hit_at_3"],
        "source_hit_at_5": quality["source_hit_at_5"],
        "mean_reciprocal_rank": quality["mean_reciprocal_rank"],
        "unstable_rankings": payload["summary"]["unstable_rankings"],
    }


def _same_ranking_count(left: dict[str, Any], right: dict[str, Any]) -> tuple[int, int]:
    left_rankings = _final_rankings(left)
    right_rankings = _final_rankings(right)
    if left_rankings.keys() != right_rankings.keys():
        raise ValueError("question IDs differ between compared runs")
    same = sum(
        left_rankings[question_id] == right_rankings[question_id]
        for question_id in left_rankings
    )
    return same, len(left_rankings)


def _candidate_changes(
    candidates_20: dict[str, Any], candidates_10: dict[str, Any]
) -> list[dict[str, Any]]:
    rankings_20 = _final_rankings(candidates_20)
    rankings_10 = _final_rankings(candidates_10)
    quality_20 = _question_quality(candidates_20)
    quality_10 = _question_quality(candidates_10)
    changes: list[dict[str, Any]] = []
    for question_id in rankings_20:
        if rankings_20[question_id] == rankings_10[question_id]:
            continue
        changes.append(
            {
                "question_id": question_id,
                "out_of_scope": quality_20[question_id]["out_of_scope"],
                "hit_rank_candidates_20": quality_20[question_id]["hit_rank"],
                "hit_rank_candidates_10": quality_10[question_id]["hit_rank"],
                "hit_at_5_candidates_20": quality_20[question_id]["hit_at_5"],
                "hit_at_5_candidates_10": quality_10[question_id]["hit_at_5"],
            }
        )
    return changes


def _ranking_comparison(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_rankings = _final_rankings(left)
    right_rankings = _final_rankings(right)
    if left_rankings.keys() != right_rankings.keys():
        raise ValueError("question IDs differ between compared runs")

    exact_ordered = 0
    same_unordered = 0
    top_1_changes: list[str] = []
    changed_questions: list[str] = []
    overlap = 0
    slots = 0
    for question_id in left_rankings:
        left_items = left_rankings[question_id]
        right_items = right_rankings[question_id]
        if left_items == right_items:
            exact_ordered += 1
        else:
            changed_questions.append(question_id)
        if set(left_items) == set(right_items):
            same_unordered += 1
        if left_items[0] != right_items[0]:
            top_1_changes.append(question_id)
        overlap += len(set(left_items) & set(right_items))
        slots += len(left_items)
    return {
        "identical_ordered_rankings": exact_ordered,
        "identical_unordered_top_k_sets": same_unordered,
        "question_count": len(left_rankings),
        "top_1_changed_questions": top_1_changes,
        "changed_questions": changed_questions,
        "top_k_overlap_items": overlap,
        "top_k_total_items": slots,
        "top_k_overlap_ratio": _round(overlap / slots),
    }


def _candidate_diversity(payload: dict[str, Any]) -> dict[str, Any]:
    unique_documents: list[int] = []
    maximum_chunks_per_document: list[int] = []
    candidate_counts: list[int] = []
    for question in payload["questions"]:
        ranking = question["runs"][0]["vector_ranking"]
        counts = Counter(item["doc_id"] for item in ranking)
        candidate_counts.append(len(ranking))
        unique_documents.append(len(counts))
        maximum_chunks_per_document.append(max(counts.values()))
    return {
        "candidate_count_min": min(candidate_counts),
        "candidate_count_max": max(candidate_counts),
        "unique_documents_mean": _round(statistics.mean(unique_documents)),
        "unique_documents_min": min(unique_documents),
        "unique_documents_max": max(unique_documents),
        "max_chunks_from_one_document": max(maximum_chunks_per_document),
    }


def build_summary(
    paths: Iterable[Path],
    manifest_path: Path,
    supplemental_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    loaded = _load_inputs(paths)
    invariants = _validate_invariants(loaded)
    manifest = _manifest_summary(manifest_path, invariants)
    rows = [_matrix_row(loaded[key]) for key in sorted(loaded)]

    cpu_gpu: list[dict[str, Any]] = []
    for backend in ("faiss-cached", "qdrant-tuned"):
        for candidates in (10, 20):
            cpu = loaded[(backend, "cpu", candidates)]
            gpu = loaded[(backend, "cuda", candidates)]
            cpu_p50 = cpu["summary"]["stages_ms"]["total"]["p50_ms"]
            gpu_p50 = gpu["summary"]["stages_ms"]["total"]["p50_ms"]
            same, total = _same_ranking_count(cpu, gpu)
            cpu_gpu.append(
                {
                    "backend": backend,
                    "initial_candidates": candidates,
                    "cpu_p50_ms": cpu_p50,
                    "gpu_p50_ms": gpu_p50,
                    "gpu_speedup_x": _round(cpu_p50 / gpu_p50),
                    "identical_final_rankings": same,
                    "question_count": total,
                    "ranking_comparison": _ranking_comparison(cpu, gpu),
                }
            )

    candidate_count: list[dict[str, Any]] = []
    for backend in ("faiss-cached", "qdrant-tuned"):
        for device in ("cpu", "cuda"):
            c20 = loaded[(backend, device, 20)]
            c10 = loaded[(backend, device, 10)]
            p50_20 = c20["summary"]["stages_ms"]["total"]["p50_ms"]
            p50_10 = c10["summary"]["stages_ms"]["total"]["p50_ms"]
            same, total = _same_ranking_count(c20, c10)
            candidate_count.append(
                {
                    "backend": backend,
                    "device": device,
                    "p50_candidates_20_ms": p50_20,
                    "p50_candidates_10_ms": p50_10,
                    "p50_reduction_percent": _round((p50_20 - p50_10) / p50_20 * 100),
                    "speedup_x": _round(p50_20 / p50_10),
                    "identical_final_rankings": same,
                    "question_count": total,
                    "ranking_comparison": _ranking_comparison(c20, c10),
                    "changed_questions": _candidate_changes(c20, c10),
                }
            )

    backend_equivalence: list[dict[str, Any]] = []
    for device in ("cpu", "cuda"):
        for candidates in (10, 20):
            faiss = loaded[("faiss-cached", device, candidates)]
            qdrant = loaded[("qdrant-tuned", device, candidates)]
            same, total = _same_ranking_count(faiss, qdrant)
            backend_equivalence.append(
                {
                    "device": device,
                    "initial_candidates": candidates,
                    "identical_final_rankings": same,
                    "question_count": total,
                    "ranking_comparison": _ranking_comparison(faiss, qdrant),
                }
            )

    supplemental: list[dict[str, Any]] = []
    for path in supplemental_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("benchmark") != "rag-backend-direct":
            raise ValueError(f"{path} is not a direct backend benchmark")
        if payload["git"]["commit"] != invariants["git_commit"] or payload["git"]["dirty"]:
            raise ValueError(f"supplemental run is not from the clean controlled commit: {path}")
        if payload["settings"]["questions_sha256"] != invariants["questions_sha256"]:
            raise ValueError(f"supplemental question SHA-256 differs: {path}")
        row = _matrix_row(
            payload
            | {
                "_source_path": path,
                "_source_sha256": _sha256(path),
            }
        )
        row["candidate_diversity"] = _candidate_diversity(payload)
        matching_tuned = loaded.get(
            (
                "qdrant-tuned",
                payload["settings"]["device"],
                int(payload["settings"]["initial_candidates"]),
            )
        )
        if matching_tuned is not None:
            row["vs_qdrant_tuned"] = _ranking_comparison(payload, matching_tuned)
            row["qdrant_tuned_candidate_diversity"] = _candidate_diversity(matching_tuned)
        supplemental.append(row)

    return {
        "schema_version": 1,
        "title": "2026-08-26 controlled RAG backend benchmark summary",
        "invariants": invariants,
        "corpus_manifest": manifest,
        "matrix": rows,
        "supplemental": supplemental,
        "comparisons": {
            "cpu_vs_gpu": cpu_gpu,
            "candidates_20_vs_10": candidate_count,
            "faiss_vs_qdrant_final_ranking_equivalence": backend_equivalence,
        },
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Eight controlled raw JSON files")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_RESULTS_DIR / "20260826_corpus-manifest.json",
    )
    parser.add_argument(
        "--supplemental",
        nargs="*",
        type=Path,
        default=[],
        help="Optional clean direct-backend runs outside the primary 8-cell matrix",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_RESULTS_DIR / "20260826_controlled-summary.json",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=DEFAULT_RESULTS_DIR / "20260826_controlled-summary.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_summary(args.inputs, args.manifest, args.supplemental)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_csv(args.csv_output, summary["matrix"])
    print(f"saved: {args.json_output}")
    print(f"saved: {args.csv_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
