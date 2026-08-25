from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_api_bench import latency_summary, source_hit_metrics  # noqa: E402


class LatencySummaryTests(unittest.TestCase):
    def test_empty_summary(self):
        self.assertEqual(latency_summary([])["samples"], 0)
        self.assertIsNone(latency_summary([])["p50_ms"])

    def test_small_sample_uses_nearest_rank_p95(self):
        summary = latency_summary([10.0, 20.0, 30.0])
        self.assertEqual(summary["samples"], 3)
        self.assertEqual(summary["p50_ms"], 20.0)
        self.assertEqual(summary["p95_ms"], 30.0)


class SourceHitMetricTests(unittest.TestCase):
    def test_first_expected_source_sets_all_hit_metrics(self):
        metrics = source_hit_metrics(
            ["expected.pdf"],
            [
                {"rank": 1, "source_file": "expected.pdf"},
                {"rank": 2, "source_file": "other.pdf"},
            ],
        )
        self.assertEqual(metrics["hit_rank"], 1)
        self.assertTrue(metrics["hit_at_1"])
        self.assertTrue(metrics["hit_at_5"])
        self.assertEqual(metrics["reciprocal_rank"], 1.0)

    def test_fourth_result_only_hits_at_five(self):
        metrics = source_hit_metrics(
            ["expected.pdf"],
            [
                {"rank": 1, "source_file": "one.pdf"},
                {"rank": 2, "source_file": "two.pdf"},
                {"rank": 3, "source_file": "three.pdf"},
                {"rank": 4, "source_file": "expected.pdf"},
            ],
        )
        self.assertFalse(metrics["hit_at_1"])
        self.assertFalse(metrics["hit_at_3"])
        self.assertTrue(metrics["hit_at_5"])
        self.assertEqual(metrics["reciprocal_rank"], 0.25)

    def test_missing_source_is_a_miss(self):
        metrics = source_hit_metrics(
            ["expected.pdf"], [{"rank": 1, "source_file": "other.pdf"}]
        )
        self.assertIsNone(metrics["hit_rank"])
        self.assertFalse(metrics["hit_at_5"])
        self.assertEqual(metrics["reciprocal_rank"], 0.0)


if __name__ == "__main__":
    unittest.main()
