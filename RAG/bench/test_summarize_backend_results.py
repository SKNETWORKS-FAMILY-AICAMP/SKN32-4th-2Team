from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

try:
    from RAG.bench.summarize_backend_results import (
        _candidate_changes,
        _ranking_comparison,
        _validate_invariants,
        build_summary,
    )
except ModuleNotFoundError:
    from summarize_backend_results import (
        _candidate_changes,
        _ranking_comparison,
        _validate_invariants,
        build_summary,
    )


BACKENDS = ("faiss-cached", "qdrant-tuned")
DEVICES = ("cpu", "cuda")
CANDIDATE_COUNTS = (10, 20)


def _ranking_item(name: str) -> dict[str, object]:
    return {
        "source_file": f"{name}.pdf",
        "page": 1,
        "content_sha256": name * 8,
    }


def _question(
    question_id: str,
    signature: str,
    ranking_names: tuple[str, ...],
    *,
    hit_rank: int | None = 1,
) -> dict[str, object]:
    return {
        "id": question_id,
        "out_of_scope": False,
        "quality": {
            "hit_rank": hit_rank,
            "hit_at_1": hit_rank == 1,
            "hit_at_3": hit_rank is not None and hit_rank <= 3,
            "hit_at_5": hit_rank is not None and hit_rank <= 5,
        },
        "runs": [
            {
                "final_ranking_signature": signature,
                "final_ranking": [_ranking_item(name) for name in ranking_names],
                "vector_ranking": [
                    {"doc_id": f"doc-{index % 2}"}
                    for index, _ in enumerate(ranking_names)
                ],
            }
        ],
    }


def _stage_summary(p50_ms: float) -> dict[str, float | int]:
    return {
        "samples": 1,
        "min_ms": p50_ms,
        "p50_ms": p50_ms,
        "p95_ms": p50_ms,
        "max_ms": p50_ms,
        "mean_ms": p50_ms,
    }


def _payload(
    backend: str,
    device: str,
    candidates: int,
    *,
    total_p50_ms: float = 100.0,
) -> dict[str, object]:
    signature = f"candidates-{candidates}"
    ranking_names = ("a", "b") if candidates == 20 else ("b", "a")
    hit_rank = 1 if candidates == 20 else 2
    return {
        "benchmark": "rag-backend-direct",
        "settings": {
            "backend": backend,
            "device": device,
            "initial_candidates": candidates,
            "questions_sha256": "questions-sha",
            "question_count": 1,
            "repeats": 1,
            "warmups": 0,
            "top_k": 2,
            "per_document": 3,
            "qdrant_fetch": 80,
        },
        "corpus": {"vector_store_count": 93, "point_count": 3681},
        "runtime": {"torch": "2.13.0+cu130"},
        "git": {"commit": "controlled-commit", "dirty": False},
        "duration_seconds": total_p50_ms / 1000,
        "initialization_ms": {
            "total": 123.0,
            "store_or_backend_build": 45.0,
        },
        "memory": {
            "rss_bytes_after_init": 1000,
            "rss_bytes_at_end": 1100,
        },
        "summary": {
            "stages_ms": {
                "total": _stage_summary(total_p50_ms),
                "embed": _stage_summary(1.0),
                "vector_search": _stage_summary(2.0),
                "bm25": _stage_summary(3.0),
                "rerank": _stage_summary(total_p50_ms - 7.0),
                "finalize": _stage_summary(1.0),
            },
            "quality": {
                "eligible_questions": 1,
                "source_hit_at_1": 1.0 if hit_rank == 1 else 0.0,
                "source_hit_at_3": 1.0,
                "source_hit_at_5": 1.0,
                "mean_reciprocal_rank": 1.0 / hit_rank,
            },
            "unstable_rankings": 0,
        },
        "questions": [
            _question(
                "question-1",
                signature,
                ranking_names,
                hit_rank=hit_rank,
            )
        ],
    }


def _loaded_matrix() -> dict[tuple[str, str, int], dict[str, object]]:
    return {
        (backend, device, candidates): _payload(backend, device, candidates)
        for backend in BACKENDS
        for device in DEVICES
        for candidates in CANDIDATE_COUNTS
    }


def _manifest() -> dict[str, object]:
    return {
        "created_at_utc": "2026-08-26T00:00:00Z",
        "git": {"commit": "controlled-commit", "dirty": False},
        "questions": {"sha256": "questions-sha"},
        "corpus": {"pdf_count": 93, "aggregate_sha256": "pdf-sha"},
        "vector_stores": {
            "store_count": 93,
            "total_chunks": 3681,
            "aggregate_sha256": "stores-sha",
        },
        "experiment_assets": {"aggregate_sha256": "assets-sha"},
        "configuration": {"top_k": 2},
        "runtime": {"python": "3.11.9"},
    }


class InvariantValidationTests(unittest.TestCase):
    def test_accepts_complete_matrix_and_returns_shared_values(self) -> None:
        invariants = _validate_invariants(_loaded_matrix())

        self.assertEqual(invariants["questions_sha256"], "questions-sha")
        self.assertEqual(invariants["point_count"], 3681)
        self.assertFalse(invariants["git_dirty"])

    def test_rejects_differing_invariant(self) -> None:
        loaded = _loaded_matrix()
        loaded[("qdrant-tuned", "cuda", 20)]["corpus"]["point_count"] = 999

        with self.assertRaisesRegex(ValueError, "invariant 'point_count' differs"):
            _validate_invariants(loaded)

    def test_rejects_incomplete_matrix(self) -> None:
        loaded = _loaded_matrix()
        del loaded[("faiss-cached", "cpu", 10)]

        with self.assertRaisesRegex(ValueError, "matrix mismatch; missing="):
            _validate_invariants(loaded)


class RankingComparisonTests(unittest.TestCase):
    def test_reports_order_set_top_one_and_overlap_changes(self) -> None:
        left = {
            "questions": [
                _question("same", "same", ("a", "b")),
                _question("reordered", "left-order", ("c", "d")),
                _question("replacement", "left-replacement", ("e", "f")),
            ]
        }
        right = {
            "questions": [
                _question("same", "same", ("a", "b")),
                _question("reordered", "right-order", ("d", "c")),
                _question("replacement", "right-replacement", ("e", "g")),
            ]
        }

        comparison = _ranking_comparison(left, right)

        self.assertEqual(comparison["identical_ordered_rankings"], 1)
        self.assertEqual(comparison["identical_unordered_top_k_sets"], 2)
        self.assertEqual(comparison["top_1_changed_questions"], ["reordered"])
        self.assertEqual(
            comparison["changed_questions"], ["reordered", "replacement"]
        )
        self.assertEqual(comparison["top_k_overlap_items"], 5)
        self.assertEqual(comparison["top_k_total_items"], 6)
        self.assertEqual(comparison["top_k_overlap_ratio"], 0.8333)

    def test_rejects_actual_ranking_changes_even_when_stored_signature_matches(self) -> None:
        unstable = _question("unstable", "same-signature", ("a", "b"))
        second_run = deepcopy(unstable["runs"][0])
        second_run["final_ranking"] = [_ranking_item("b"), _ranking_item("a")]
        unstable["runs"].append(second_run)

        with self.assertRaisesRegex(ValueError, "unstable final rankings"):
            _ranking_comparison(
                {"questions": [unstable]},
                {"questions": [_question("unstable", "same-signature", ("a", "b"))]},
            )

    def test_candidate_changes_include_quality_shift_only_for_changed_rankings(self) -> None:
        candidates_20 = {
            "questions": [
                _question("same", "same", ("a", "b"), hit_rank=1),
                _question("changed", "c20", ("c", "d"), hit_rank=4),
            ]
        }
        candidates_10 = {
            "questions": [
                _question("same", "same", ("a", "b"), hit_rank=1),
                _question("changed", "c10", ("d", "c"), hit_rank=2),
            ]
        }

        self.assertEqual(
            _candidate_changes(candidates_20, candidates_10),
            [
                {
                    "question_id": "changed",
                    "out_of_scope": False,
                    "hit_rank_candidates_20": 4,
                    "hit_rank_candidates_10": 2,
                    "hit_at_5_candidates_20": True,
                    "hit_at_5_candidates_10": True,
                }
            ],
        )


class BuildSummaryTests(unittest.TestCase):
    def _write_matrix(self, root: Path) -> list[Path]:
        paths: list[Path] = []
        p50_by_device_candidates = {
            ("cpu", 20): 200.0,
            ("cpu", 10): 100.0,
            ("cuda", 20): 20.0,
            ("cuda", 10): 10.0,
        }
        for backend in BACKENDS:
            for device in DEVICES:
                for candidates in CANDIDATE_COUNTS:
                    path = root / f"{backend}-{device}-{candidates}.json"
                    payload = _payload(
                        backend,
                        device,
                        candidates,
                        total_p50_ms=p50_by_device_candidates[(device, candidates)],
                    )
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    paths.append(path)
        return paths

    def test_builds_eight_cell_matrix_and_expected_comparisons(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._write_matrix(root)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")

            summary = build_summary(paths, manifest_path)

        self.assertEqual(len(summary["matrix"]), 8)
        self.assertEqual(len(summary["comparisons"]["cpu_vs_gpu"]), 4)
        self.assertEqual(
            len(summary["comparisons"]["candidates_20_vs_10"]), 4
        )
        self.assertEqual(
            len(
                summary["comparisons"][
                    "faiss_vs_qdrant_final_ranking_equivalence"
                ]
            ),
            4,
        )
        for comparison in summary["comparisons"]["cpu_vs_gpu"]:
            self.assertEqual(comparison["gpu_speedup_x"], 10.0)
            self.assertEqual(comparison["identical_final_rankings"], 1)
        for comparison in summary["comparisons"]["candidates_20_vs_10"]:
            self.assertEqual(comparison["p50_reduction_percent"], 50.0)
            self.assertEqual(comparison["speedup_x"], 2.0)
            self.assertEqual(comparison["identical_final_rankings"], 0)
            self.assertEqual(
                [item["question_id"] for item in comparison["changed_questions"]],
                ["question-1"],
            )

    def test_rejects_manifest_question_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = self._write_matrix(root)
            manifest = deepcopy(_manifest())
            manifest["questions"]["sha256"] = "different-sha"
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "manifest question SHA-256 differs",
            ):
                build_summary(paths, manifest_path)


if __name__ == "__main__":
    unittest.main()
