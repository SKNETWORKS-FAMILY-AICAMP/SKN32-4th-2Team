from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from app.services.answer_policy import evaluate_clarification


CRITICAL_IDS = {
    "leave-parental-a",
    "leave-parental-b",
    "work-flexible-a",
    "work-hours",
    "pay-severance",
    "pay-holiday-work",
    "hire-contract-b",
    "disc-dui-a",
    "disc-dui-b",
}


class CriticalQualityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        questions_path = Path(__file__).resolve().parents[1] / "bench" / "questions.yaml"
        rows = yaml.safe_load(questions_path.read_text(encoding="utf-8"))["questions"]
        cls.cases = {row["id"]: row for row in rows if row.get("severity") == "critical"}

    def test_all_nine_critical_cases_have_behavior_labels(self) -> None:
        self.assertEqual(set(self.cases), CRITICAL_IDS)
        for case in self.cases.values():
            with self.subTest(case=case["id"]):
                self.assertIn("expected_action", case)
                self.assertTrue(case.get("must_not_claim"))

    def test_every_clarification_case_is_intercepted_before_rag(self) -> None:
        for case in self.cases.values():
            if case["expected_action"] != "clarify":
                continue
            with self.subTest(case=case["id"]):
                decision = evaluate_clarification(case["question"])
                self.assertTrue(decision.needs_clarification, case["question"])
                self.assertTrue(decision.question)


if __name__ == "__main__":
    unittest.main()
