"""LLM 답변을 검색 근거에 묶고, 위험한 초안을 사용자에게 내보내기 전에 검증한다.

프롬프트 준수는 확률적이다. 이 모듈은 답변 상태와 ``[E1]`` 형태의 근거 ID를
검사하되, ID 출력 형식 자체를 사용자 답변의 성공 조건으로 삼지는 않는다. ID가
빠지면 검색 근거를 서버가 보수적으로 연결하고 의미 검증을 강제한다. 숫자·기간·
비율·조문은 연결된 청크에 실제 문자열이 있어야 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Sequence

from app.domain import RetrievedChunk

DraftStatus = Literal["ANSWER", "CLARIFY", "NOT_FOUND", "RAG_UNAVAILABLE"]

_STATUS_RE = re.compile(
    r"^\s*\[?\s*상태\s*:\s*(ANSWER|CLARIFY|NOT_FOUND|RAG_UNAVAILABLE)\s*\]?\s*",
    re.IGNORECASE,
)
_EVIDENCE_RE = re.compile(r"\[E(\d+)\]", re.IGNORECASE)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_CLARIFY_POLICY_CLAIM = re.compile(
    r"(?:누구나|모두|항상|반드시|해당\s*직원).{0,20}"
    r"(?:가능|대상|사용|적용|지급|산정|받)"
    r"|(?:가능|대상|적용|지급|산정|사용할\s*수|받을\s*수)\s*"
    r"(?:있|없|입니다|이다|합니다|된다|됩니다)(?:지만|으나|고|며|므로)?",
)
_NONCLAIM_SCAFFOLD = re.compile(
    r"^(?:답변|안내|근무시간|출퇴근\s*시간|출근\s*시간|퇴근\s*시간)\s*[:：]?$"
    r"|^(?:.+?은\s*)?(?:다음과\s*같습니다|아래와\s*같습니다|다음과\s*같이\s*안내드립니다)\s*[:：.]?$"
)

# 숫자가 들어간 모든 문자열을 막으면 문서명 버전이나 목록 번호까지 오탐한다. HR 안내에서
# 특히 위험한 기간·비율·금액·횟수·조문만 뽑아 해당 근거 청크와 대조한다.
_NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"
_UNIT = r"(?:년|개월|월|주|일|시간|시|분|회|명|세|%|퍼센트|배|원|만원|학년)"

_RISKY_TOKEN_RE = re.compile(
    r"제\s*\d+\s*조(?:\s*의\s*\d+)?"
    r"|\d{4}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}"
    r"|\d{1,2}\s*:\s*\d{2}\s*(?:~|∼|～|–|—|-)\s*\d{1,2}\s*:\s*\d{2}"
    rf"|{_NUMBER}\s*{_UNIT}?\s*(?:~|∼|～|–|—|-|부터|에서)\s*{_NUMBER}\s*{_UNIT}"
    r"|100\s*분의\s*\d+(?:\.\d+)?"
    rf"|{_NUMBER}\s*{_UNIT}",
    re.IGNORECASE,
)

# 규정 원문에서 기간을 ``년누계 2월``처럼 쓰는 경우가 있다. 여기서 ``월``은
# 달력의 2월(February)이 아니라 기간 2개월이라는 뜻이다. 모델이 이를 자연스러운
# 한국어인 ``연간 2개월``로 풀어 써도 같은 근거로 보되, 일반적인 ``2월``까지
# 바꾸면 시행일 같은 달력 날짜를 잘못 통과시키므로 ``년/연 + 누계`` 문맥만 좁게
# 정규화한다.
_CUMULATIVE_MONTH_DURATION_RE = re.compile(
    rf"((?:년|연)\s*누계\s*)({_NUMBER})\s*월(?=\s|의|간|범위|[,.]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class GroundingResult:
    """검증된 사용자 표시용 답변과 실제로 사용한 근거 번호."""

    status: DraftStatus | None
    text: str
    evidence_numbers: tuple[int, ...]
    errors: tuple[str, ...]
    implicit_evidence: bool = False

    @property
    def valid(self) -> bool:
        return not self.errors and self.status is not None and bool(self.text)


def _compact(text: str) -> str:
    compact = re.sub(r"[\s,]", "", text or "").lower()
    compact = compact.replace("퍼센트", "%")
    return compact.translate(str.maketrans({"∼": "~", "～": "~", "–": "~", "—": "~"}))


def _body_and_status(raw: str) -> tuple[DraftStatus | None, str]:
    match = _STATUS_RE.match(raw or "")
    if not match:
        return None, (raw or "").strip()
    status = match.group(1).upper()
    body = (raw or "")[match.end() :].strip()
    return status, body  # type: ignore[return-value]


def _segments(body: str) -> list[str]:
    # 자연스러운 출력은 ``문장입니다. [E1]``처럼 마침표 뒤에 근거 ID가 온다.
    # 분리 전에 검증용 복사본에서만 ID를 마침표 앞으로 옮겨 해당 문장과 묶는다.
    attached = re.sub(
        r"([.!?。！？])\s*((?:\[E\d+\]\s*)+)",
        r"\2\1 ",
        body,
        flags=re.IGNORECASE,
    )

    return [part.strip(" \t-*•") for part in _SENTENCE_BOUNDARY.split(attached) if part.strip()]


def _risk_tokens(text: str) -> tuple[str, ...]:
    normalized = _CUMULATIVE_MONTH_DURATION_RE.sub(r"\1\2개월", text or "")
    return tuple(match.group(0) for match in _RISKY_TOKEN_RE.finditer(normalized))


def _matching_evidence_numbers(
    text: str,
    chunks: Sequence[RetrievedChunk],
) -> tuple[int, ...]:
    """위험 토큰이 모두 직접 들어 있는 청크를 순위 순서로 반환한다."""

    required = {_compact(token) for token in _risk_tokens(text)}
    if not required:
        return ()
    matched: list[int] = []
    for number, chunk in enumerate(chunks, 1):
        available = {_compact(token) for token in _risk_tokens(chunk.content)}
        if required.issubset(available):
            matched.append(number)
    return tuple(matched)


def validate_answer(
    raw: str,
    chunks: Sequence[RetrievedChunk],
    *,
    degraded: bool = False,
) -> GroundingResult:
    """상태·근거 ID·위험 수치의 직접 근거를 검사한다.

    ``ANSWER``의 근거 ID가 빠진 문장은 검색 청크에 보수적으로 연결하고, 호출자가
    의미 검증을 강제할 수 있도록 ``implicit_evidence``를 표시한다. ``CLARIFY``와
    ``NOT_FOUND``는 정책 내용을 덧붙일 수 없도록 근거 ID와 위험 수치를 금지한다.
    """

    status, body = _body_and_status(raw)
    errors: list[str] = []
    if status is None:
        errors.append("첫 줄에 답변 상태가 없습니다")
    if not body:
        errors.append("답변 본문이 비어 있습니다")

    if degraded and status != "RAG_UNAVAILABLE":
        errors.append("RAG 조회 실패 상태에서는 RAG_UNAVAILABLE만 사용할 수 있습니다")
    if not degraded and status == "RAG_UNAVAILABLE":
        errors.append("정상 RAG 조회에서 RAG_UNAVAILABLE을 사용할 수 없습니다")

    refs = tuple(dict.fromkeys(int(value) for value in _EVIDENCE_RE.findall(body)))
    valid_refs = tuple(number for number in refs if 1 <= number <= len(chunks))
    resolved_refs = list(valid_refs)
    implicit_evidence = False
    invalid_refs = [number for number in refs if number < 1 or number > len(chunks)]
    if invalid_refs:
        errors.append(f"존재하지 않는 근거 ID: {invalid_refs}")

    if status == "ANSWER":
        if not chunks:
            errors.append("검색 근거 없이 ANSWER 상태를 사용했습니다")

        for segment in _segments(body):
            segment_refs = tuple(int(value) for value in _EVIDENCE_RE.findall(segment))
            visible = _EVIDENCE_RE.sub("", segment).strip()
            if not visible:
                continue
            if not segment_refs:
                # 제목이나 "다음과 같습니다:" 같은 도입은 정책 주장이 아니다. 이런
                # 짧은 scaffold는 의미 검증 대상 문장으로 취급하지 않는다.
                if not _risk_tokens(visible) and _NONCLAIM_SCAFFOLD.fullmatch(visible):
                    continue
                implicit_evidence = True
                inferred_refs = _matching_evidence_numbers(visible, chunks)
                if inferred_refs:
                    valid_segment_refs = list(inferred_refs)
                elif _risk_tokens(visible):
                    # 한 문장이 여러 청크의 조건을 함께 요약할 수 있으므로, 위험 수치가
                    # 한 청크에 모두 모이지 않으면 검색 근거 전체와 대조한다.
                    valid_segment_refs = list(valid_refs or range(1, len(chunks) + 1))
                else:
                    # 수치 없는 설명은 최상위 검색 근거를 우선 연결하고 아래 의미
                    # verifier가 실제 주장까지 검증한다.
                    valid_segment_refs = list(valid_refs or ((1,) if chunks else ()))
            else:
                valid_segment_refs = [
                    number for number in segment_refs if 1 <= number <= len(chunks)
                ]

            for number in valid_segment_refs:
                if number not in resolved_refs:
                    resolved_refs.append(number)
            evidence_text = "\n".join(chunks[number - 1].content for number in valid_segment_refs)
            evidence_tokens = {_compact(token) for token in _risk_tokens(evidence_text)}
            for token in _risk_tokens(visible):
                # 부분 문자열 비교는 근거의 ``11일``로 답변의 ``1일``을 통과시킨다.
                # 같은 위험 토큰 추출기를 양쪽에 적용한 뒤 완전 일치만 허용한다.
                if _compact(token) not in evidence_tokens:
                    errors.append(f"직접 근거에 없는 수치·조문: {token}")

        if chunks and not resolved_refs:
            # 본문이 제목뿐이거나 모델이 전혀 인용하지 않은 예외도 의미 검증 없이
            # 통과시키지 않는다.
            resolved_refs.append(1)
            implicit_evidence = True

    elif status in {"CLARIFY", "NOT_FOUND", "RAG_UNAVAILABLE"}:
        if refs:
            errors.append(f"{status} 상태에는 근거 ID를 붙일 수 없습니다")
        tokens = _risk_tokens(body)
        if tokens:
            errors.append(f"{status} 상태에 규정 수치·조문이 포함됐습니다: {tokens[0]}")
        if status == "CLARIFY":
            segments = _segments(body)
            if len(segments) != 1:
                errors.append("CLARIFY는 확인 질문 한 문장만 허용합니다")
            if _CLARIFY_POLICY_CLAIM.search(body):
                errors.append("CLARIFY 상태에 확인 전 정책 주장이 포함됐습니다")
            if body and not (
                body.rstrip().endswith(("?", "？"))
                or re.search(
                    r"(?:나요|까요|인가요|건가요|말씀인가요|알려주세요|말씀해주세요|"
                    r"확인해주세요|선택해주세요)\s*[.]?$",
                    body,
                )
            ):
                errors.append("CLARIFY 본문이 확인 질문 형식이 아닙니다")

    clean = _EVIDENCE_RE.sub("", body)
    clean = re.sub(r"[ \t]+([.!?,。！？])", r"\1", clean)
    clean = re.sub(r"[ \t]{2,}", " ", clean).strip()
    return GroundingResult(
        status=status,
        text=clean,
        evidence_numbers=tuple(resolved_refs),
        errors=tuple(dict.fromkeys(errors)),
        implicit_evidence=implicit_evidence,
    )


def repair_instruction(errors: Sequence[str]) -> str:
    """검증 실패 초안을 한 번만 고치도록 주는 짧은 피드백."""

    details = "\n".join(f"- {error}" for error in errors[:8])
    return (
        "[답변 검증 실패]\n"
        f"{details}\n"
        "위 오류를 모두 고쳐 답변 전체를 다시 작성하세요. 반드시 [상태: ...]로 시작하고, "
        "ANSWER는 제목·도입문·목록 머리·근거 없는 마무리를 쓰지 마세요. 상태 줄을 제외한 "
        "모든 보이는 문장과 줄 끝에는 그 내용을 직접 뒷받침하는 [E번호]를 붙이세요. "
        "근거에 없는 내용은 삭제하고, 적용 대상이 불명확하면 CLARIFY로 바꾸세요."
    )
