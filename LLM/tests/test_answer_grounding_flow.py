from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.domain import RetrievedChunk
from app.providers.base import GenerationResult
from app.schemas import ChatRequest, HistoryTurn
from app.services.answer import build_search_query, expand_retrieval_query, generate_answer


def _request(message: str) -> ChatRequest:
    return ChatRequest(chatroom_id="room-1", message=message)


class _Provider:
    name = "test"
    model = "test-model"

    def __init__(self, *texts: str) -> None:
        self.generate = AsyncMock(
            side_effect=[GenerationResult(text=text, model=self.model) for text in texts]
        )
        self.classify = AsyncMock(return_value="SUPPORTED")


class AnswerGroundingFlowTests(unittest.IsolatedAsyncioTestCase):
    def test_clock_question_expands_to_normal_and_flexible_work_types(self) -> None:
        expanded = expand_retrieval_query("교직원 출근시간은 몇시야?")

        self.assertIn("기본 근무시간", expanded)
        self.assertIn("시차출퇴근제", expanded)
        for work_type in ("A형", "B형", "C형", "D형", "E형"):
            self.assertIn(work_type, expanded)

    def test_non_clock_question_is_not_expanded(self) -> None:
        question = "출장 신청 절차를 알려줘"
        self.assertEqual(expand_retrieval_query(question), question)

    def test_annual_leave_count_variants_prioritize_leave_rules(self) -> None:
        for question in (
            "연차 사용 가능일수는 며칠이야?",
            "연차사용 가능일수는 며칠이야?",
            "연차 며칠까지 쓸 수 있나요?",
        ):
            with self.subTest(question=question):
                expanded = expand_retrieval_query(question)
                self.assertIn("복무규정", expanded)
                self.assertIn("연차휴가", expanded)
                self.assertIn("재직기간", expanded)

    def test_annual_leave_allowance_question_is_not_rewritten_as_leave_days(self) -> None:
        question = "연차수당은 며칠까지 지급되나요?"
        self.assertEqual(expand_retrieval_query(question), question)

    def test_search_query_does_not_mix_an_unrelated_previous_topic(self) -> None:
        history = [
            HistoryTurn(speaker="user", message="음주운전을 하면 어떤 처분을 받나요?"),
            HistoryTurn(speaker="llm", message="적발 횟수와 사고 여부를 알려주세요."),
        ]
        current = "법정 근로시간은 주 몇 시간인가요?"
        self.assertEqual(build_search_query(current, history), current)

    def test_search_query_keeps_context_for_a_clarification_reply(self) -> None:
        history = [
            HistoryTurn(speaker="user", message="육아휴직은 얼마나 쓸 수 있나요?"),
            HistoryTurn(speaker="llm", message="신청하려는 분의 직군을 알려주세요."),
        ]
        self.assertEqual(
            build_search_query("기술연구원이요", history),
            "육아휴직은 얼마나 쓸 수 있나요? 기술연구원이요",
        )

    def test_search_query_keeps_context_for_an_explicit_followup(self) -> None:
        history = [HistoryTurn(speaker="user", message="연차는 며칠인가요?")]
        self.assertEqual(
            build_search_query("그럼 반차는요?", history),
            "연차는 며칠인가요? 그럼 반차는요?",
        )

    def test_search_query_accumulates_multi_step_clarification_replies(self) -> None:
        history = [
            HistoryTurn(speaker="user", message="음주운전을 하면 어떤 처분을 받나요?"),
            HistoryTurn(speaker="llm", message="적발 횟수, 농도, 사고 여부를 알려주세요."),
            HistoryTurn(speaker="user", message="초범이고 사고는 없었습니다"),
            HistoryTurn(speaker="llm", message="혈중알코올농도를 알려주세요."),
        ]

        self.assertEqual(
            build_search_query("0.05%입니다", history),
            "음주운전을 하면 어떤 처분을 받나요? 초범이고 사고는 없었습니다 0.05%입니다",
        )

    def test_explicit_followup_keeps_a_completed_clarification_topic(self) -> None:
        history = [
            HistoryTurn(speaker="user", message="육아휴직은 얼마나 쓸 수 있나요?"),
            HistoryTurn(speaker="llm", message="신청하려는 분의 직군을 알려주세요."),
            HistoryTurn(speaker="user", message="기술연구원이요"),
            HistoryTurn(speaker="llm", message="근거에 따른 기간 답변"),
        ]

        self.assertEqual(
            build_search_query("그럼 신청 절차는요?", history),
            "육아휴직은 얼마나 쓸 수 있나요? 기술연구원이요 그럼 신청 절차는요?",
        )

    async def test_ambiguous_query_returns_clarification_before_rag_or_llm(self) -> None:
        with (
            patch("app.services.answer.get_provider") as get_provider,
            patch("app.services.answer._retrieve", new=AsyncMock()) as retrieve,
            patch("app.services.answer.metrics.record_chat"),
        ):
            response = await generate_answer(_request("유연근무제는 어떻게 신청하나요?"))

        self.assertEqual(response.answer_status, "clarification_required")
        self.assertIn("어떤 유형", response.answer)
        get_provider.assert_not_called()
        retrieve.assert_not_awaited()

    async def test_previous_topic_does_not_hijack_a_new_question(self) -> None:
        request = ChatRequest(
            chatroom_id="room-1",
            message="법정 근로시간은 주 몇 시간인가요?",
            history=[
                {"speaker": "user", "message": "음주운전을 하면 어떤 처분을 받나요?"},
                {"speaker": "llm", "message": "적발 횟수와 사고 여부를 알려주세요."},
            ],
        )
        provider = _Provider("[상태: NOT_FOUND]\n제공된 문서에서 찾을 수 없습니다.")
        settings = SimpleNamespace(
            llm_timeout_sec=15.0,
            answer_max_tokens=500,
            answer_cite_articles=False,
            answer_verify_mode="off",
        )
        with (
            patch("app.services.answer.get_settings", return_value=settings),
            patch("app.services.answer.get_provider", return_value=provider) as get_provider,
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=([], False, 0)),
            ),
            patch(
                "app.services.answer.classify",
                new=AsyncMock(return_value=("근태/근무형태", False)),
            ),
            patch("app.services.answer.metrics.record_chat"),
            patch("app.services.answer.metrics.record", new=Mock()),
        ):
            response = await generate_answer(request)

        get_provider.assert_called_once()
        self.assertEqual(response.topic, "근태/근무형태")

    async def test_rag_failure_returns_without_calling_the_llm(self) -> None:
        with (
            patch("app.services.answer.get_provider") as get_provider,
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=([], True, 25)),
            ),
            patch("app.services.answer.metrics.record_chat"),
        ):
            response = await generate_answer(_request("법정 근로시간을 알려주세요"))

        get_provider.assert_not_called()
        self.assertEqual(response.answer_status, "rag_unavailable")
        self.assertTrue(response.rag_degraded)

    async def test_only_cited_evidence_is_exposed_as_source(self) -> None:
        chunks = [
            RetrievedChunk(
                "근로기준법.pdf",
                "1주 간의 근로시간은 40시간을 초과할 수 없다.",
                doc_id=1,
                page=1,
            ),
            RetrievedChunk("무관한규정.pdf", "다른 내용", doc_id=2, page=3),
        ]
        provider = _Provider("[상태: ANSWER]\n주당 근로시간은 40시간입니다. [E1]")
        settings = SimpleNamespace(
            llm_timeout_sec=15.0,
            answer_max_tokens=500,
            answer_cite_articles=False,
            answer_verify_mode="risky",
        )

        with (
            patch("app.services.answer.get_settings", return_value=settings),
            patch("app.services.answer.get_provider", return_value=provider),
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=(chunks, False, 10)),
            ),
            patch(
                "app.services.answer.classify",
                new=AsyncMock(return_value=("근태/근무형태", False)),
            ),
            patch("app.services.answer.metrics.record_chat"),
            patch("app.services.answer.metrics.record", new=Mock()),
        ):
            response = await generate_answer(_request("법정 근로시간은 주 몇 시간인가요?"))

        self.assertEqual(response.answer_status, "answered")
        self.assertEqual(response.answer, "주당 근로시간은 40시간입니다.")
        self.assertEqual([source.original_file_name for source in response.sources], ["근로기준법.pdf"])
        self.assertEqual(provider.generate.await_count, 1)

    async def test_invalid_draft_is_repaired_once(self) -> None:
        chunks = [
            RetrievedChunk(
                "휴일근로규정.pdf",
                "휴일근로에 통상임금의 100분의 50을 가산한다.",
                doc_id=1,
                page=1,
            )
        ]
        provider = _Provider(
            "[상태: ANSWER]\n휴일근로수당은 150%입니다. [E1]",
            "[상태: ANSWER]\n휴일근로에는 통상임금의 100분의 50을 가산합니다. [E1]",
        )
        settings = SimpleNamespace(
            llm_timeout_sec=15.0,
            answer_max_tokens=500,
            answer_cite_articles=False,
            answer_verify_mode="risky",
        )

        with (
            patch("app.services.answer.get_settings", return_value=settings),
            patch("app.services.answer.get_provider", return_value=provider),
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=(chunks, False, 10)),
            ),
            patch(
                "app.services.answer.classify",
                new=AsyncMock(return_value=("급여/보수", False)),
            ),
            patch("app.services.answer.metrics.record_chat"),
            patch("app.services.answer.metrics.record", new=Mock()),
        ):
            response = await generate_answer(
                _request("공휴일에 실제 근무한 경우 수당은 어떻게 산정되나요?")
            )

        self.assertEqual(provider.generate.await_count, 2)
        self.assertEqual(response.answer_status, "answered")
        self.assertIn("100분의 50", response.answer)
        self.assertNotIn("150%", response.answer)

    async def test_semantically_unsupported_range_is_repaired(self) -> None:
        chunks = [
            RetrievedChunk(
                "음주운전지침.pdf",
                "초범이며 사고가 없는 경우 징계 범위는 정직~해임이다.",
                doc_id=1,
                page=1,
            )
        ]
        provider = _Provider(
            "[상태: ANSWER]\n징계는 감봉 또는 해임입니다. [E1]",
            "[상태: ANSWER]\n징계 범위는 정직~해임입니다. [E1]",
        )
        provider.classify.side_effect = ["UNSUPPORTED", "SUPPORTED"]
        settings = SimpleNamespace(
            llm_timeout_sec=15.0,
            answer_max_tokens=500,
            answer_cite_articles=False,
            answer_verify_mode="risky",
        )

        with (
            patch("app.services.answer.get_settings", return_value=settings),
            patch("app.services.answer.get_provider", return_value=provider),
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=(chunks, False, 10)),
            ),
            patch(
                "app.services.answer.classify",
                new=AsyncMock(return_value=("징계/행동강령", False)),
            ),
            patch("app.services.answer.metrics.record_chat"),
            patch("app.services.answer.metrics.record", new=Mock()),
        ):
            response = await generate_answer(
                _request(
                    "초범이고 혈중알코올농도 0.05%이며 사고가 없는 음주운전의 징계 기준은?"
                )
            )

        self.assertEqual(provider.generate.await_count, 2)
        self.assertEqual(provider.classify.await_count, 2)
        self.assertEqual(response.answer_status, "answered")
        self.assertIn("정직~해임", response.answer)
        self.assertNotIn("감봉", response.answer)

    async def test_clarification_reply_keeps_original_risky_intent_for_verifier(self) -> None:
        chunks = [
            RetrievedChunk(
                "음주운전지침.pdf",
                "초범이며 사고가 없는 경우 징계 범위는 정직~해임이다.",
                doc_id=1,
                page=1,
            )
        ]
        provider = _Provider(
            "[상태: ANSWER]\n징계는 감봉 또는 해임입니다. [E1]",
            "[상태: ANSWER]\n징계 범위는 정직~해임입니다. [E1]",
        )
        provider.classify.side_effect = ["UNSUPPORTED", "SUPPORTED"]
        settings = SimpleNamespace(
            llm_timeout_sec=15.0,
            answer_max_tokens=500,
            answer_cite_articles=False,
            answer_verify_mode="risky",
        )
        request = ChatRequest(
            chatroom_id="room-1",
            message="초범이고 혈중알코올농도 0.05%이며 사고는 없었습니다",
            history=[
                {"speaker": "user", "message": "음주운전을 하면 어떤 처분을 받나요?"},
                {"speaker": "llm", "message": "적발 횟수, 농도, 사고 여부를 알려주세요."},
            ],
        )
        topic_classifier = AsyncMock(return_value=("징계/행동강령", False))

        with (
            patch("app.services.answer.get_settings", return_value=settings),
            patch("app.services.answer.get_provider", return_value=provider),
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=(chunks, False, 10)),
            ),
            patch(
                "app.services.answer.classify",
                new=topic_classifier,
            ),
            patch("app.services.answer.metrics.record_chat"),
            patch("app.services.answer.metrics.record", new=Mock()),
        ):
            response = await generate_answer(request)

        self.assertEqual(provider.classify.await_count, 2)
        verifier_input = provider.classify.await_args_list[0].kwargs["user_content"]
        self.assertIn("음주운전을 하면 어떤 처분을 받나요?", verifier_input)
        self.assertIn(
            "음주운전을 하면 어떤 처분을 받나요?",
            topic_classifier.await_args.args[0],
        )
        self.assertEqual(response.answer_status, "answered")
        self.assertIn("정직~해임", response.answer)

    async def test_partial_clarification_reply_asks_only_for_remaining_dui_detail(self) -> None:
        request = ChatRequest(
            chatroom_id="room-1",
            message="초범이고 사고는 없었습니다",
            history=[
                {"speaker": "user", "message": "음주운전을 하면 어떤 처분을 받나요?"},
                {"speaker": "llm", "message": "적발 횟수, 농도, 사고 여부를 알려주세요."},
            ],
        )
        with (
            patch("app.services.answer.get_provider") as get_provider,
            patch("app.services.answer._retrieve", new=AsyncMock()) as retrieve,
            patch("app.services.answer.metrics.record_chat"),
        ):
            response = await generate_answer(request)

        self.assertEqual(response.answer_status, "clarification_required")
        self.assertIn("혈중알코올농도", response.answer)
        self.assertNotIn("적발 횟수", response.answer)
        self.assertNotIn("사고 여부", response.answer)
        get_provider.assert_not_called()
        retrieve.assert_not_awaited()

    async def test_work_hours_false_refusal_is_repaired_from_direct_evidence(self) -> None:
        chunks = [
            RetrievedChunk(
                "근로기준법.pdf",
                "제50조 근로시간은 1주 40시간, 1일 8시간을 초과할 수 없다.",
                doc_id=1,
                page=1,
            )
        ]
        provider = _Provider(
            "[상태: NOT_FOUND]\n제공된 문서에서 찾을 수 없습니다.",
            "[상태: ANSWER]\n법정 근로시간은 1주 40시간, 1일 8시간입니다. [E1]",
        )
        provider.classify.side_effect = ["UNSUPPORTED", "SUPPORTED"]
        settings = SimpleNamespace(
            llm_timeout_sec=15.0,
            answer_max_tokens=500,
            answer_cite_articles=False,
            answer_verify_mode="risky",
        )

        with (
            patch("app.services.answer.get_settings", return_value=settings),
            patch("app.services.answer.get_provider", return_value=provider),
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=(chunks, False, 10)),
            ),
            patch(
                "app.services.answer.classify",
                new=AsyncMock(return_value=("근태/근무형태", False)),
            ),
            patch("app.services.answer.metrics.record_chat"),
            patch("app.services.answer.metrics.record", new=Mock()),
        ):
            response = await generate_answer(_request("법정 근로시간은 주 몇 시간인가요?"))

        self.assertEqual(response.answer_status, "answered")
        self.assertIn("40시간", response.answer)
        self.assertIn("8시간", response.answer)

    async def test_severance_hallucinated_period_and_article_are_removed(self) -> None:
        chunks = [
            RetrievedChunk(
                "퇴직급여규정.pdf",
                "퇴직급여의 적용 대상과 지급 절차는 별도의 규정에 따른다.",
                doc_id=1,
                page=1,
            )
        ]
        provider = _Provider(
            "[상태: ANSWER]\n근로기준법 제47조에 따라 직전 3개월 평균임금으로 산정합니다. [E1]",
            "[상태: NOT_FOUND]\n제공된 문서에서 정확한 산식을 찾을 수 없습니다.",
        )
        provider.classify.return_value = "SUPPORTED"
        settings = SimpleNamespace(
            llm_timeout_sec=15.0,
            answer_max_tokens=500,
            answer_cite_articles=False,
            answer_verify_mode="risky",
        )

        with (
            patch("app.services.answer.get_settings", return_value=settings),
            patch("app.services.answer.get_provider", return_value=provider),
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=(chunks, False, 10)),
            ),
            patch(
                "app.services.answer.classify",
                new=AsyncMock(return_value=("급여/보수", False)),
            ),
            patch("app.services.answer.metrics.record_chat"),
            patch("app.services.answer.metrics.record", new=Mock()),
        ):
            response = await generate_answer(_request("퇴직금은 어떤 기준으로 산정되나요?"))

        self.assertEqual(response.answer_status, "not_found")

    async def test_implicit_evidence_forces_semantic_verification_even_when_mode_off(self) -> None:
        chunks = [
            RetrievedChunk(
                "복무규정.pdf",
                "교직원은 시무시간 전에 근무처에 도착하여 근무자세를 갖추어야 한다.",
                doc_id=1,
                page=2,
            )
        ]
        provider = _Provider(
            "[상태: ANSWER]\n교직원은 시무시간 전에 근무처에 도착해야 합니다."
        )
        settings = SimpleNamespace(
            llm_timeout_sec=15.0,
            answer_max_tokens=500,
            answer_cite_articles=False,
            answer_verify_mode="off",
        )

        with (
            patch("app.services.answer.get_settings", return_value=settings),
            patch("app.services.answer.get_provider", return_value=provider),
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=(chunks, False, 10)),
            ),
            patch(
                "app.services.answer.classify",
                new=AsyncMock(return_value=("근태/근무형태", False)),
            ),
            patch("app.services.answer.metrics.record_chat"),
            patch("app.services.answer.metrics.record", new=Mock()),
        ):
            response = await generate_answer(_request("교직원의 출근 원칙을 알려주세요"))

        self.assertEqual(response.answer_status, "answered")
        self.assertEqual(provider.generate.await_count, 1)
        self.assertEqual(provider.classify.await_count, 1)
        self.assertEqual(len(response.sources), 1)

    async def test_uncited_but_grounded_annual_leave_answer_is_returned(self) -> None:
        chunks = [
            RetrievedChunk(
                "복무규정.pdf",
                "1년 미만 또는 1년간 80퍼센트 미만 출근한 교직원은 1개월 "
                "개근 시 1일, 1년간 80퍼센트 이상 출근한 교직원은 15일, "
                "3년 이상 재직하면 2년마다 1일을 가산하되 총 25일을 한도로 한다.",
                doc_id=1,
                page=4,
            ),
            RetrievedChunk("연차수당규칙.pdf", "연차수당은 14일을 한도로 한다.", doc_id=2),
        ]
        provider = _Provider(
            "[상태: ANSWER]\n"
            "1년 미만이거나 출근율이 80% 미만이면 1개월 개근 시 1일입니다.\n"
            "1년간 80% 이상 출근하면 15일입니다.\n"
            "3년 이상 재직하면 2년마다 1일을 가산하며 최대 25일입니다."
        )
        settings = SimpleNamespace(
            llm_timeout_sec=15.0,
            answer_max_tokens=500,
            answer_cite_articles=False,
            answer_verify_mode="risky",
        )

        with (
            patch("app.services.answer.get_settings", return_value=settings),
            patch("app.services.answer.get_provider", return_value=provider),
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=(chunks, False, 10)),
            ),
            patch(
                "app.services.answer.classify",
                new=AsyncMock(return_value=("휴가/휴직", False)),
            ),
            patch("app.services.answer.metrics.record_chat"),
            patch("app.services.answer.metrics.record", new=Mock()),
        ):
            response = await generate_answer(_request("연차 사용 가능일수는 며칠이야?"))

        self.assertEqual(response.answer_status, "answered")
        self.assertIn("15일", response.answer)
        self.assertIn("25일", response.answer)
        self.assertEqual(provider.generate.await_count, 1)
        self.assertEqual(provider.classify.await_count, 1)
        self.assertEqual(
            [source.original_file_name for source in response.sources],
            ["복무규정.pdf"],
        )
        self.assertNotIn("3개월", response.answer)
        self.assertNotIn("제47조", response.answer)

    async def test_unrepairable_draft_is_not_misreported_as_document_absence(self) -> None:
        chunks = [RetrievedChunk("복무규정.pdf", "직원의 복무 기준을 정한다.", page=1)]
        provider = _Provider(
            "답변 형식이 잘못되었습니다.",
            "교정 후에도 상태와 근거가 없습니다.",
        )
        settings = SimpleNamespace(
            llm_timeout_sec=15.0,
            answer_max_tokens=500,
            answer_cite_articles=False,
            answer_verify_mode="risky",
        )

        with (
            patch("app.services.answer.get_settings", return_value=settings),
            patch("app.services.answer.get_provider", return_value=provider),
            patch(
                "app.services.answer._retrieve",
                new=AsyncMock(return_value=(chunks, False, 10)),
            ),
            patch(
                "app.services.answer.classify",
                new=AsyncMock(return_value=("근태/근무형태", False)),
            ),
            patch("app.services.answer.metrics.record_chat"),
            patch("app.services.answer.metrics.record", new=Mock()),
        ):
            response = await generate_answer(_request("복무 기준을 알려주세요"))

        self.assertEqual(response.answer_status, "verification_failed")
        self.assertIn("근거를 충분히 검증하지 못했습니다", response.answer)
        self.assertNotIn("찾을 수 없습니다", response.answer)


if __name__ == "__main__":
    unittest.main()
