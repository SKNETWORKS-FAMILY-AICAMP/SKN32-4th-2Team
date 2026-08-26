from __future__ import annotations

import unittest

from app.services.evidence_verifier import should_verify


class EvidenceVerifierRoutingTests(unittest.TestCase):
    def test_risky_mode_includes_annual_leave_and_working_hours_wording(self) -> None:
        self.assertTrue(should_verify("연차는 며칠인가요?", "ANSWER", "risky"))
        self.assertTrue(
            should_verify("법정 근무시간은 주 몇 시간인가요?", "ANSWER", "risky")
        )

    def test_non_policy_question_is_skipped_in_risky_mode(self) -> None:
        self.assertFalse(should_verify("오늘 날씨가 어떤가요?", "NOT_FOUND", "risky"))

    def test_common_high_risk_synonyms_are_verified(self) -> None:
        for question in (
            "월급은 어떻게 계산하나요?",
            "연봉 산정 기준은 무엇인가요?",
            "병가는 누가 사용할 수 있나요?",
            "상여금 지급 기준은 무엇인가요?",
            "성과급은 어떻게 정해지나요?",
        ):
            with self.subTest(question=question):
                self.assertTrue(should_verify(question, "ANSWER", "risky"))

    def test_high_risk_clarification_is_semantically_verified(self) -> None:
        self.assertTrue(
            should_verify("병가 적용 직군을 알려주세요", "CLARIFY", "risky")
        )


if __name__ == "__main__":
    unittest.main()
