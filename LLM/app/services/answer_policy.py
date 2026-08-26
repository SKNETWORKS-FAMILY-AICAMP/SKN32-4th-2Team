"""Deterministic clarification policy for high-risk HR questions.

This module does not answer policy questions.  It only decides whether a small,
explicit set of ambiguous questions needs another user turn before retrieval or
answer generation.  Keeping this decision deterministic prevents the language
model from silently choosing an employee category or event scenario.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClarificationDecision:
    """Result of the pre-answer ambiguity check."""

    needs_clarification: bool
    question: str | None = None
    code: str | None = None
    reason: str | None = None


_CLEAR = ClarificationDecision(needs_clarification=False)


def _compact(text: str) -> str:
    """Normalize spacing and common separators without losing numeric detail."""

    return re.sub(r"[\s_\-./·]+", "", text).lower()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


_EMPLOYEE_TYPES = (
    "일반직원",
    "일반직",
    "직원",
    "정규직",
    "공무직",
    "계약직",
    "기간제근로자",
    "근로자",
    "행정직",
    "강사",
    "임시교원",
    "기간제교원",
    "교원",
    "교사",
    "교수",
    "기술연구원",
    "연구원",
)

_FLEXIBLE_WORK_SUBTYPES = (
    "재택근무",
    "재택",
    "원격근무",
    "원격",
    "시차출퇴근",
    "탄력근무",
    "탄력적근로",
    "선택근무",
    "선택적근로",
    "시간선택",
    "집중근무",
    "자율출퇴근",
    "간주근로",
)

_FIXED_TERM_EMPLOYEE_TYPES = (
    "일반기간제",
    "기간제직원",
    "기간제근로자",
    "기간제사원",
    "직원",
    "근로자",
    "사원",
    "행정직",
    "연구직",
)

_FIXED_TERM_TEACHER_TYPES = (
    "기간제교원",
    "기간제교사",
    "교원",
    "교사",
    "강사",
    "교수",
)


def _is_parental_leave_question(text: str) -> bool:
    if "육아휴직" in text:
        return True
    return bool(
        re.search(
            r"(?:아이|자녀).{0,12}(?:돌봄|돌보|양육|키우).{0,12}(?:휴직|쉬)",
            text,
        )
    )


def _is_flexible_work_application(text: str) -> bool:
    return "유연근무" in text and _contains_any(
        text,
        ("신청", "절차", "방법", "어떻게", "사용", "이용"),
    )


def _is_fixed_term_hiring(text: str) -> bool:
    return "기간제" in text and _contains_any(
        text,
        ("채용", "고용", "임용", "뽑"),
    )


def _is_holiday_pay_question(text: str) -> bool:
    has_holiday = _contains_any(text, ("공휴일", "법정휴일", "휴일"))
    has_pay = _contains_any(text, ("급여", "임금", "수당", "보수", "가산"))
    return has_holiday and has_pay


def _has_holiday_work_status(text: str) -> bool:
    worked = _contains_any(
        text,
        (
            "휴일근로",
            "공휴일근무",
            "공휴일에근무",
            "공휴일에일",
            "근무했",
            "근무한",
            "근로했",
            "근로한",
            "일했",
            "일한경우",
            "출근",
        ),
    )
    did_not_work = _contains_any(
        text,
        (
            "유급휴일",
            "쉬는공휴일",
            "공휴일에쉬",
            "휴무",
            "근무하지",
            "근로하지",
            "출근하지",
            "일하지",
        ),
    )
    return worked or did_not_work


def _is_dui_discipline_question(text: str) -> bool:
    return "음주운전" in text and _contains_any(
        text,
        ("징계", "처분", "조치", "기준", "받"),
    )


def _dui_missing_details(text: str) -> list[str]:
    has_occurrence = _contains_any(
        text,
        (
            "초범",
            "첫적발",
            "최초적발",
            "1회",
            "1차",
            "한번",
            "두번째",
            "2회",
            "2차",
            "재범",
            "상습",
            "적발횟수",
            "과거적발",
        ),
    )
    has_level_or_license = _contains_any(
        text,
        (
            "혈중알코올",
            "알코올농도",
            "면허정지",
            "면허취소",
            "측정거부",
        ),
    )
    has_accident_status = _contains_any(
        text,
        (
            "사고",
            "무사고",
            "인명피해",
            "물적피해",
            "상해",
            "사망",
            "뺑소니",
        ),
    )

    missing: list[str] = []
    if not has_occurrence:
        missing.append("적발 횟수(초범·재범 여부)")
    if not has_level_or_license:
        missing.append("혈중알코올농도 또는 면허 처분·측정거부 여부")
    if not has_accident_status:
        missing.append("인적·물적 사고 여부")
    return missing


def evaluate_clarification(query: str) -> ClarificationDecision:
    """Return a clarification request for supported high-risk ambiguities.

    An empty query and questions outside the five deliberately supported cases
    pass through.  The caller remains responsible for all other intent, safety,
    retrieval, and answer validation decisions.
    """

    text = _compact(query or "")
    if not text:
        return _CLEAR

    if _is_parental_leave_question(text) and not _contains_any(
        text, _EMPLOYEE_TYPES
    ):
        return ClarificationDecision(
            needs_clarification=True,
            code="parental_leave_employee_type",
            reason="육아휴직 적용 규정을 선택할 직군 정보가 없습니다.",
            question=(
                "육아휴직을 신청하려는 분의 직군을 알려주세요. "
                "예: 일반 직원, 강사·교원, 기술연구원"
            ),
        )

    if _is_flexible_work_application(text) and not _contains_any(
        text, _FLEXIBLE_WORK_SUBTYPES
    ):
        return ClarificationDecision(
            needs_clarification=True,
            code="flexible_work_subtype",
            reason="신청하려는 유연근무 유형이 지정되지 않았습니다.",
            question=(
                "어떤 유형의 유연근무를 신청하려는지 알려주세요. "
                "예: 재택근무, 시차출퇴근, 탄력근무"
            ),
        )

    if _is_fixed_term_hiring(text) and not (
        _contains_any(text, _FIXED_TERM_EMPLOYEE_TYPES)
        or _contains_any(text, _FIXED_TERM_TEACHER_TYPES)
    ):
        return ClarificationDecision(
            needs_clarification=True,
            code="fixed_term_hire_category",
            reason="기간제 채용 대상이 일반 직원인지 교원인지 구분되지 않았습니다.",
            question="채용 대상이 일반 기간제 직원인가요, 기간제 교원인가요?",
        )

    if _is_holiday_pay_question(text) and not _has_holiday_work_status(text):
        return ClarificationDecision(
            needs_clarification=True,
            code="holiday_pay_work_status",
            reason="공휴일에 실제로 근무했는지가 분명하지 않습니다.",
            question=(
                "공휴일에 실제로 근무한 경우의 수당을 묻는 것인가요, "
                "근무하지 않고 쉬는 공휴일의 임금을 묻는 것인가요?"
            ),
        )

    if _is_dui_discipline_question(text):
        missing = _dui_missing_details(text)
        if missing:
            return ClarificationDecision(
                needs_clarification=True,
                code="dui_discipline_event_details",
                reason="음주운전 징계 기준을 구분할 사건 정보가 부족합니다.",
                question="다음 정보를 알려주세요: " + ", ".join(missing),
            )

    return _CLEAR


def is_clarification_reply(code: str | None, query: str) -> bool:
    """Return whether ``query`` supplies a slot requested by ``code``.

    The WEB currently persists only speaker/message history, not a separate
    clarification code.  Re-evaluating the previous user turn gives the search
    layer enough information to join replies such as ``기술연구원이요`` to the
    original question without joining every unrelated new question.
    """

    text = _compact(query or "")
    if not code or not text:
        return False
    if code == "parental_leave_employee_type":
        return _contains_any(text, _EMPLOYEE_TYPES)
    if code == "flexible_work_subtype":
        return _contains_any(text, _FLEXIBLE_WORK_SUBTYPES)
    if code == "fixed_term_hire_category":
        return _contains_any(
            text,
            _FIXED_TERM_EMPLOYEE_TYPES + _FIXED_TERM_TEACHER_TYPES,
        )
    if code == "holiday_pay_work_status":
        return _has_holiday_work_status(text)
    if code == "dui_discipline_event_details":
        # The reply need not contain the word 음주운전 again; any one of the
        # requested dimensions is useful context for the original question.
        has_bare_alcohol_level = bool(re.search(r"\d+(?:\.\d+)?%", text))
        return len(_dui_missing_details(text)) < 3 or has_bare_alcohol_level
    return False


__all__ = [
    "ClarificationDecision",
    "evaluate_clarification",
    "is_clarification_reply",
]
