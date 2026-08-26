"""고위험 HR 답변의 의미적 근거 충족 여부를 구조화 enum으로 판정한다."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from app.domain import RetrievedChunk
from app.services.grounding import DraftStatus

VerifyMode = Literal["off", "risky", "all"]

VERIFIER_SYSTEM = """당신은 HR 규정 답변의 근거 감사자입니다.
반드시 SUPPORTED 또는 UNSUPPORTED 중 하나만 선택합니다.

SUPPORTED 조건:
- ANSWER의 모든 사실·수치·기간·비율·절차·적용 대상이 그 문장이 인용한 근거에 있다.
- 서로 다른 직군이나 제도를 섞지 않았다.
- 조건·예외·표의 범위와 중간 선택지를 중요한 의미 변화 없이 보존했다.
- NOT_FOUND라면 제공된 근거에 질문의 직접 답이 실제로 없다.
- CLARIFY라면 규정 사실을 먼저 단정하지 않고 필요한 정보만 한 문장으로 질문한다.

하나라도 충족하지 않거나 판단 근거가 부족하면 UNSUPPORTED입니다. 일반상식이나 기억으로
빈 부분을 채우지 마세요. 답변 문체·친절함은 평가하지 말고 근거 충족만 평가합니다."""

_RISKY_TERMS = (
    "급여",
    "임금",
    "수당",
    "퇴직",
    "보수",
    "휴직",
    "휴가",
    "연차",
    "연가",
    "병가",
    "근로시간",
    "근무시간",
    "출근시간",
    "퇴근시간",
    "출퇴근",
    "월급",
    "연봉",
    "상여금",
    "성과급",
    "유연근무",
    "채용",
    "임용",
    "계약",
    "징계",
    "처분",
    "해고",
    "음주운전",
)


def should_verify(question: str, status: DraftStatus | None, mode: VerifyMode) -> bool:
    if mode == "off" or status not in {"ANSWER", "NOT_FOUND", "CLARIFY"}:
        return False
    if mode == "all":
        return True
    compact = "".join((question or "").split())
    return any(term in compact for term in _RISKY_TERMS)


def build_verifier_input(
    *,
    question: str,
    raw_answer: str,
    chunks: Sequence[RetrievedChunk],
    evidence_numbers: Sequence[int],
    status: DraftStatus | None,
) -> str:
    # NOT_FOUND의 오거절을 판단할 때는 검색된 근거 전체가 필요하다. ANSWER는 모델이
    # 실제 인용한 근거만 보여줘 다른 청크에서 우연히 뒷받침되는 것을 막는다.
    if status == "NOT_FOUND":
        selected = list(enumerate(chunks, 1))
    else:
        selected = [
            (number, chunks[number - 1])
            for number in evidence_numbers
            if 1 <= number <= len(chunks)
        ]

    evidence_blocks = []
    for number, chunk in selected:
        metadata = [f"문서={chunk.original_file_name}"]
        if chunk.audience:
            metadata.append(f"적용대상={','.join(chunk.audience)}")
        if chunk.article:
            metadata.append(f"조문={chunk.article}")
        evidence_blocks.append(
            f"[E{number} {'; '.join(metadata)}]\n{chunk.content}"
        )

    evidence_text = "\n\n".join(evidence_blocks) or "(근거 없음)"
    return (
        f"[질문]\n{question}\n\n"
        f"[검증할 초안]\n{raw_answer}\n\n"
        f"[허용된 근거]\n{evidence_text}"
    )
