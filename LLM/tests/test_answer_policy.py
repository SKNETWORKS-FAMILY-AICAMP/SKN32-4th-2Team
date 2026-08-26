from __future__ import annotations

import unittest

from app.services.answer_policy import evaluate_clarification, is_clarification_reply


class AnswerPolicyTests(unittest.TestCase):
    def assertClarifies(self, query: str, code: str) -> None:  # noqa: N802
        decision = evaluate_clarification(query)
        self.assertTrue(decision.needs_clarification)
        self.assertEqual(decision.code, code)
        self.assertTrue(decision.question)
        self.assertTrue(decision.reason)

    def assertPasses(self, query: str) -> None:  # noqa: N802
        decision = evaluate_clarification(query)
        self.assertFalse(decision.needs_clarification)
        self.assertIsNone(decision.code)
        self.assertIsNone(decision.question)
        self.assertIsNone(decision.reason)

    def test_parental_leave_requires_employee_type(self) -> None:
        self.assertClarifies(
            "육아휴직은 얼마나 쓸 수 있나요?",
            "parental_leave_employee_type",
        )
        self.assertClarifies(
            "아이를 돌보려고 휴직하려는데 기간이 어떻게 되나요?",
            "parental_leave_employee_type",
        )

    def test_parental_leave_passes_with_employee_type(self) -> None:
        for query in (
            "일반 직원의 육아휴직 신청 절차를 알려주세요",
            "기술연구원은 육아휴직을 얼마나 쓸 수 있나요?",
            "기간제 교원의 육아휴직 규정이 궁금합니다",
        ):
            with self.subTest(query=query):
                self.assertPasses(query)

    def test_flexible_work_application_requires_subtype(self) -> None:
        self.assertClarifies(
            "유연근무제는 어떻게 신청하나요?",
            "flexible_work_subtype",
        )

    def test_flexible_work_passes_with_subtype_or_non_application_intent(self) -> None:
        for query in (
            "재택근무는 어떻게 신청하나요?",
            "시차출퇴근 유연근무 신청 절차를 알려주세요",
            "유연근무에는 어떤 종류가 있나요?",
        ):
            with self.subTest(query=query):
                self.assertPasses(query)

    def test_fixed_term_hiring_requires_employee_or_teacher_category(self) -> None:
        self.assertClarifies(
            "기간제로 사람을 뽑으려면 어떤 기준을 따라야 하나요?",
            "fixed_term_hire_category",
        )

    def test_fixed_term_hiring_passes_with_target_category(self) -> None:
        for query in (
            "기간제 근로자를 채용할 때 어떤 기준을 따르나요?",
            "기간제 교원을 임용하는 절차를 알려주세요",
        ):
            with self.subTest(query=query):
                self.assertPasses(query)

    def test_holiday_pay_requires_work_status(self) -> None:
        self.assertClarifies(
            "공휴일에 대한 급여는 어떻게 산정돼요?",
            "holiday_pay_work_status",
        )

    def test_holiday_pay_passes_when_work_status_is_explicit(self) -> None:
        for query in (
            "공휴일에 8시간 근무했는데 수당은 어떻게 계산하나요?",
            "공휴일에 근무하지 않고 쉬면 임금은 어떻게 되나요?",
            "유급휴일 임금 산정 방법을 알려주세요",
        ):
            with self.subTest(query=query):
                self.assertPasses(query)

    def test_dui_discipline_requires_event_details(self) -> None:
        self.assertClarifies(
            "음주운전을 하면 어떤 처분을 받나요?",
            "dui_discipline_event_details",
        )
        partial = evaluate_clarification(
            "초범 음주운전이고 사고는 없었는데 징계 기준이 어떻게 되나요?"
        )
        self.assertTrue(partial.needs_clarification)
        self.assertIn("혈중알코올농도", partial.question or "")
        self.assertNotIn("적발 횟수", partial.question or "")
        self.assertNotIn("사고 여부", partial.question or "")

    def test_dui_discipline_passes_with_all_event_details(self) -> None:
        for query in (
            "초범이고 혈중알코올농도 0.05%이며 사고 없는 음주운전의 징계 기준은?",
            "재범 음주운전으로 면허취소됐고 인명 사고가 있으면 어떤 처분인가요?",
        ):
            with self.subTest(query=query):
                self.assertPasses(query)

    def test_unrelated_queries_are_not_intercepted(self) -> None:
        for query in (
            "연차는 며칠인가요?",
            "음주운전 예방 교육 일정을 알려주세요",
            "기간제 계약 종료일을 확인하고 싶어요",
            "법정 근로시간은 주 몇 시간인가요?",
            "퇴직금 산정 기준을 알려주세요",
            "",
        ):
            with self.subTest(query=query):
                self.assertPasses(query)

    def test_clarification_reply_matches_only_the_requested_slot(self) -> None:
        self.assertTrue(
            is_clarification_reply(
                "parental_leave_employee_type",
                "기술연구원이요",
            )
        )
        self.assertFalse(
            is_clarification_reply(
                "parental_leave_employee_type",
                "법정 근로시간은 주 몇 시간인가요?",
            )
        )
        self.assertTrue(
            is_clarification_reply(
                "dui_discipline_event_details",
                "초범이고 0.05%이며 사고는 없었습니다",
            )
        )
        self.assertTrue(
            is_clarification_reply(
                "dui_discipline_event_details",
                "0.05%입니다",
            )
        )


if __name__ == "__main__":
    unittest.main()
