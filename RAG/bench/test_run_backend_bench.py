from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_backend_bench import (  # noqa: E402
    apply_per_document_limit,
    euclid_to_squared_l2,
    latency_summary,
    quality_summary,
    source_hit_metrics,
)


class PerDocumentDiversityTests(unittest.TestCase):
    def test_keeps_distance_order_and_caps_each_document(self):
        candidates = [
            {"doc_id": "a", "marker": 1},
            {"doc_id": "a", "marker": 2},
            {"doc_id": "a", "marker": 3},
            {"doc_id": "a", "marker": 4},
            {"doc_id": "b", "marker": 5},
            {"doc_id": "b", "marker": 6},
            {"doc_id": "c", "marker": 7},
        ]
        selected = apply_per_document_limit(
            candidates, per_document=2, limit=5
        )
        self.assertEqual([item["marker"] for item in selected], [1, 2, 5, 6, 7])

    def test_stops_at_candidate_limit(self):
        candidates = [{"doc_id": str(index)} for index in range(10)]
        self.assertEqual(len(apply_per_document_limit(candidates, limit=3)), 3)


class DistanceMetricTests(unittest.TestCase):
    def test_qdrant_euclid_is_squared_for_faiss_comparison(self):
        self.assertAlmostEqual(euclid_to_squared_l2(3.0), 9.0)
        self.assertAlmostEqual(euclid_to_squared_l2(0.125), 0.015625)


class SummaryTests(unittest.TestCase):
    def test_latency_summary_uses_nearest_rank_p95(self):
        summary = latency_summary([10.0, 20.0, 30.0])
        self.assertEqual(summary["samples"], 3)
        self.assertEqual(summary["p50_ms"], 20.0)
        self.assertEqual(summary["p95_ms"], 30.0)

    def test_source_metrics_and_quality_summary_exclude_out_of_scope(self):
        first = source_hit_metrics(
            ["expected.pdf"], [{"source_file": "expected.pdf"}]
        )
        fourth = source_hit_metrics(
            ["expected.pdf"],
            [
                {"source_file": "one.pdf"},
                {"source_file": "two.pdf"},
                {"source_file": "three.pdf"},
                {"source_file": "expected.pdf"},
            ],
        )
        miss = source_hit_metrics(
            ["expected.pdf"], [{"source_file": "other.pdf"}]
        )
        records = [
            {"expected_sources": ["expected.pdf"], "out_of_scope": False, "quality": first},
            {"expected_sources": ["expected.pdf"], "out_of_scope": False, "quality": fourth},
            {"expected_sources": ["expected.pdf"], "out_of_scope": False, "quality": miss},
            {"expected_sources": ["expected.pdf"], "out_of_scope": True, "quality": first},
            {"expected_sources": [], "out_of_scope": False, "quality": None},
        ]
        summary = quality_summary(records)
        self.assertEqual(summary["eligible_questions"], 3)
        self.assertEqual(summary["source_hit_at_1"], round(1 / 3, 6))
        self.assertEqual(summary["source_hit_at_3"], round(1 / 3, 6))
        self.assertEqual(summary["source_hit_at_5"], round(2 / 3, 6))
        self.assertEqual(summary["mean_reciprocal_rank"], round(1.25 / 3, 6))


if __name__ == "__main__":
    unittest.main()
