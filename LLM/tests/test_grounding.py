from __future__ import annotations

import unittest

from app.domain import RetrievedChunk
from app.services.grounding import validate_answer


class GroundingValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = [
            RetrievedChunk(
                "근로기준법.pdf",
                "[제50조(근로시간)] 1주 간의 근로시간은 휴게시간을 제외하고 40시간을 "
                "초과할 수 없다. 1일의 근로시간은 8시간을 초과할 수 없다.",
                page=12,
            ),
            RetrievedChunk(
                "휴일근로규정.pdf",
                "휴일근로에 대하여 통상임금의 100분의 50을 가산하여 지급한다.",
                page=3,
            ),
        ]

    def test_grounded_numeric_answer_passes(self) -> None:
        result = validate_answer(
            "[상태: ANSWER]\n주당 근로시간은 40시간이고 1일은 8시간입니다. [E1]",
            self.chunks,
        )

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.status, "ANSWER")
        self.assertEqual(result.evidence_numbers, (1,))
        self.assertNotIn("[E1]", result.text)

    def test_number_must_exist_in_the_cited_chunk(self) -> None:
        result = validate_answer(
            "[상태: ANSWER]\n휴일근로수당은 150%입니다. [E2]",
            self.chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("150%" in error for error in result.errors))

    def test_numeric_evidence_requires_a_complete_token_match(self) -> None:
        chunks = [RetrievedChunk("규정.pdf", "휴직기간은 11일입니다.")]
        result = validate_answer(
            "[상태: ANSWER]\n휴직기간은 1일입니다. [E1]",
            chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("1일" in error for error in result.errors))

    def test_money_with_thousands_separator_requires_full_token_match(self) -> None:
        chunks = [RetrievedChunk("규정.pdf", "지원 한도는 1,000만원입니다.")]
        result = validate_answer(
            "[상태: ANSWER]\n지원 한도는 2,000만원입니다. [E1]",
            chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("2,000만원" in error for error in result.errors))

    def test_numeric_range_requires_both_endpoints_to_match(self) -> None:
        chunks = [RetrievedChunk("규정.pdf", "사용 기간은 1~3년입니다.")]
        result = validate_answer(
            "[상태: ANSWER]\n사용 기간은 2~3년입니다. [E1]",
            chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("2~3년" in error for error in result.errors))

    def test_article_number_cannot_be_borrowed_from_another_chunk(self) -> None:
        result = validate_answer(
            "[상태: ANSWER]\n휴일근로수당은 제50조에 따릅니다. [E2]",
            self.chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("제50조" in error for error in result.errors))

    def test_uncited_hallucinated_number_is_still_rejected(self) -> None:
        result = validate_answer(
            "[상태: ANSWER]\n주당 근로시간은 40시간입니다. [E1]\n"
            "일반적으로 퇴직 직전 3개월을 사용합니다.",
            self.chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("3개월" in error for error in result.errors))

    def test_nonclaim_heading_does_not_discard_grounded_answer(self) -> None:
        result = validate_answer(
            "[상태: ANSWER]\n교직원의 출근 시간은 다음과 같습니다:\n"
            "주당 근로시간은 40시간입니다. [E1]",
            self.chunks,
        )

        self.assertTrue(result.valid, result.errors)

    def test_uncited_substantive_sentence_uses_implicit_evidence(self) -> None:
        result = validate_answer(
            "[상태: ANSWER]\n교직원은 사전 승인을 받아야 합니다.\n"
            "주당 근로시간은 40시간입니다. [E1]",
            self.chunks,
        )

        self.assertTrue(result.valid, result.errors)
        self.assertTrue(result.implicit_evidence)
        self.assertEqual(result.evidence_numbers, (1,))

    def test_uncited_annual_leave_conditions_match_the_direct_chunk(self) -> None:
        chunks = [
            RetrievedChunk(
                "복무규정.pdf",
                "1년 미만 또는 1년간 80퍼센트 미만 출근한 교직원은 1개월 "
                "개근 시 1일, 1년간 80퍼센트 이상 출근한 교직원은 15일, "
                "총휴가일수는 25일을 한도로 한다.",
            ),
            RetrievedChunk("연차수당규칙.pdf", "연차수당은 14일을 한도로 한다."),
        ]
        result = validate_answer(
            "[상태: ANSWER]\n1년간 80% 이상 출근하면 15일입니다. "
            "총 연차 한도는 25일입니다.",
            chunks,
        )

        self.assertTrue(result.valid, result.errors)
        self.assertTrue(result.implicit_evidence)
        self.assertEqual(result.evidence_numbers, (1,))

    def test_clock_time_with_direct_evidence_passes(self) -> None:
        chunks = [
            RetrievedChunk(
                "복무규정.pdf",
                "교직원의 1일 근무시간은 09시부터 18시까지로 하며 "
                "점심시간은 12시부터 13시까지로 한다.",
            )
        ]
        result = validate_answer(
            "[상태: ANSWER]\n교직원의 근무시간은 09시부터 18시까지입니다. [E1] "
            "점심시간은 12시부터 13시까지입니다. [E1]",
            chunks,
        )

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.evidence_numbers, (1,))

    def test_wrong_clock_time_is_rejected(self) -> None:
        chunks = [
            RetrievedChunk(
                "복무규정.pdf",
                "교직원의 1일 근무시간은 09시부터 18시까지로 한다.",
            )
        ]
        result = validate_answer(
            "[상태: ANSWER]\n교직원의 근무시간은 08시부터 17시까지입니다. [E1]",
            chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("08시부터 17시" in error for error in result.errors))

    def test_flexible_work_clock_range_accepts_equivalent_wave_dash(self) -> None:
        chunks = [
            RetrievedChunk(
                "유연근무제 운영지침.pdf",
                "A형은 07:30～16:30, B형은 08:00～17:00이다.",
            )
        ]
        result = validate_answer(
            "[상태: ANSWER]\nA형은 07:30~16:30, B형은 08:00~17:00입니다. [E1]",
            chunks,
        )

        self.assertTrue(result.valid, result.errors)

    def test_wrong_flexible_work_clock_range_is_rejected(self) -> None:
        chunks = [
            RetrievedChunk(
                "유연근무제 운영지침.pdf",
                "A형은 07:30～16:30이다.",
            )
        ]
        result = validate_answer(
            "[상태: ANSWER]\nA형은 07:00~16:00입니다. [E1]",
            chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("07:00~16:00" in error for error in result.errors))

    def test_legal_cumulative_month_wording_matches_natural_month_duration(self) -> None:
        chunks = [
            RetrievedChunk(
                "복무규정.pdf",
                "제21조(병가) 교직원이 질병 또는 부상으로 직무를 수행할 수 없을 때에는 "
                "년누계 2월의 범위 안에서 유급의 병가를 허가할 수 있다. 연간 6일을 "
                "초과하는 병가에는 의사의 진단서를 첨부하여야 한다.",
            )
        ]
        result = validate_answer(
            "[상태: ANSWER]\n병가는 연간 2개월 범위에서 허가할 수 있으며, "
            "6일을 초과하면 의사의 진단서가 필요합니다. [E1]",
            chunks,
        )

        self.assertTrue(result.valid, result.errors)

    def test_cumulative_two_months_does_not_license_sixty_day_conversion(self) -> None:
        chunks = [RetrievedChunk("복무규정.pdf", "병가는 년누계 2월의 범위에서 허가한다.")]
        result = validate_answer(
            "[상태: ANSWER]\n병가는 연간 60일까지 사용할 수 있습니다. [E1]",
            chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("60일" in error for error in result.errors))

    def test_calendar_february_is_not_treated_as_two_month_duration(self) -> None:
        chunks = [RetrievedChunk("시행규정.pdf", "이 규정은 2026년 2월부터 시행한다.")]
        result = validate_answer(
            "[상태: ANSWER]\n시행 기간은 2개월입니다. [E1]",
            chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("2개월" in error for error in result.errors))

    def test_not_found_cannot_smuggle_a_percentage(self) -> None:
        result = validate_answer(
            "[상태: NOT_FOUND]\n근거는 찾지 못했지만 일반적으로 150%입니다.",
            self.chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("150%" in error for error in result.errors))

    def test_clarification_has_no_policy_claim(self) -> None:
        result = validate_answer(
            "[상태: CLARIFY]\n일반 직원과 기간제 교원 중 어느 쪽인가요?",
            self.chunks,
        )

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.status, "CLARIFY")
        self.assertEqual(result.evidence_numbers, ())

    def test_clarification_accepts_natural_request_ending(self) -> None:
        result = validate_answer(
            "[상태: CLARIFY]\n적용 직군을 알려주세요.",
            self.chunks,
        )

        self.assertTrue(result.valid, result.errors)

    def test_clarification_rejects_policy_claim_before_the_question(self) -> None:
        for text in (
            "육아휴직은 누구나 가능하지만 어느 직군인가요?",
            "해당 직원은 육아휴직 대상이지만 어느 직군인가요?",
            "병가는 사용할 수 있지만 계약직인지 알려주세요.",
        ):
            with self.subTest(text=text):
                result = validate_answer(f"[상태: CLARIFY]\n{text}", self.chunks)
                self.assertFalse(result.valid)
                self.assertTrue(any("정책 주장" in error for error in result.errors))

    def test_unknown_evidence_id_is_rejected(self) -> None:
        result = validate_answer(
            "[상태: ANSWER]\n주당 근로시간은 40시간입니다. [E99]",
            self.chunks,
        )

        self.assertFalse(result.valid)
        self.assertTrue(any("존재하지 않는 근거 ID" in error for error in result.errors))

    def test_rag_state_and_answer_status_cannot_contradict(self) -> None:
        unavailable = validate_answer(
            "[상태: NOT_FOUND]\n제공된 문서에서 찾을 수 없습니다.",
            [],
            degraded=True,
        )
        false_alarm = validate_answer(
            "[상태: RAG_UNAVAILABLE]\n잠시 후 다시 시도해주세요.",
            [],
            degraded=False,
        )

        self.assertFalse(unavailable.valid)
        self.assertFalse(false_alarm.valid)


if __name__ == "__main__":
    unittest.main()
