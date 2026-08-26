"""답변 생성 오케스트레이션.

순서: 모호성 확인 → RAG 검색 → 답변 생성 → 근거 검증/1회 교정 → 응답 조립.
주제 분류는 보조 작업으로 동시에 시작하지만, 답변 검증 시간이나 성공 여부에는
영향을 주지 않도록 짧게 기다린 뒤 실패하면 기본 주제로 대체한다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Sequence

from app import metrics
from app.config import get_settings
from app.domain import FALLBACK_TOPIC, TOPIC_MAX_LEN, RetrievedChunk
from app.errors import (
    LLMServiceError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.prompts import ANSWER_SYSTEM, build_answer_context
from app.providers.base import Message
from app.providers.registry import get_provider
from app.schemas import ChatRequest, ChatResponse, HistoryTurn
from app.services import rag_client
from app.services.answer_policy import evaluate_clarification, is_clarification_reply
from app.services.evidence_verifier import (
    VERIFIER_SYSTEM,
    build_verifier_input,
    should_verify,
)
from app.services.grounding import GroundingResult, repair_instruction, validate_answer
from app.services.topic import classify

logger = logging.getLogger(__name__)

# 근거에 없는 조문 인용을 답변에서 걷어낸다.
#
# 왜 필요한가
# -----------
# RAG 청크가 조문 중간부터 시작해 `제N조` 머리가 컨텍스트에 없는 경우가 잦다.
# 그러면 모델이 조 번호를 기억으로 붙인다. 실측(같은 질문 8회)에서 이렇게 나왔다.
#
#   "(근로기준법 제2항)"    조 번호 없이 항만 — 법령에서 특정 불가
#   "(근로기준법 제57조)"   제57조는 보상 휴가제로, 휴일근로수당과 무관
#
# 두 번째가 특히 위험하다. 형식이 멀쩡해서 직원이 그대로 믿고 엉뚱한 조문을
# 찾아간다. 규정 안내 서비스에서 잘못된 출처는 없는 것만 못하다.
#
# 프롬프트로 "근거에 보이는 조문만 인용하라" 고 지시했지만 확률적으로 샌다.
# **검증은 코드로 하는 편이 확실하다** — 검색된 청크 본문에 그 조 번호가
# 있는지 그냥 대조하면 된다.
#
# 인용을 통째로 없애지 않는 이유: 맞는 인용은 가치가 크다. "근로기준법에
# 따르면" 과 "근로기준법 제60조에 따르면" 은 직원이 원문을 찾아볼 수 있느냐가
# 다르다. 그래서 **지어낸 것만** 지운다.
_ARTICLE_NUMBER = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?")
# 지울 때는 **앞 공백까지 함께** 먹는다. "근로기준법 제57조에" → "근로기준법에".
# 공백 정리를 문서 전체에 돌리면 "1년 이상" 이 "1년이상" 이 되는 식으로 멀쩡한
# 곳을 망친다. 지운 자리에서만 처리해야 안전하다.
_ARTICLE_WITH_SPACE = re.compile(r"\s?(제\s*\d+\s*조(?:\s*의\s*\d+)?)")
_BARE_CLAUSE_WITH_SPACE = re.compile(r"\s?(제\s*\d+\s*[항호])")
# 인용만 담긴 괄호. 안을 지우면 빈 껍데기가 남으므로 함께 정리한다.
_EMPTY_PAREN = re.compile(r"[(（]\s*[)）]")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def strip_unverifiable_citations(text: str, context: str, *, allow: bool = True) -> str:
    """근거에서 확인되지 않는 조문 번호를 답변에서 지운다.

    문장을 통째로 지우지 않고 **번호만** 뺀다. "근로기준법 제57조에 따르면" 은
    "근로기준법에 따르면" 이 되어 문장이 그대로 살아 있고 뜻도 안 바뀐다.

    `allow=False` 면 근거에 있든 없든 조문 번호를 전부 뺀다. 지금 RAG 구성에서
    쓰는 값이다 — 이유는 `Settings.answer_cite_articles` 주석 참조.
    """
    if not text:
        return text

    flat_context = _normalize(context)

    def _drop_if_unverifiable(match: re.Match) -> str:
        # group(1) 이 조문 번호, group(0) 은 앞 공백까지 포함한다.
        if not allow:
            return ""
        return match.group(0) if _normalize(match.group(1)) in flat_context else ""

    cleaned = _ARTICLE_WITH_SPACE.sub(_drop_if_unverifiable, text)

    # 조 번호가 하나도 안 남았는데 항·호만 떠 있으면 그것도 지운다.
    # 조문 없이 "제2항" 만으로는 법령에서 찾을 수 없다.
    if not _ARTICLE_NUMBER.search(cleaned):
        cleaned = _BARE_CLAUSE_WITH_SPACE.sub("", cleaned)

    if cleaned == text:
        return text

    # 인용만 들어 있던 괄호가 빈 껍데기로 남으면 지운다.
    cleaned = re.sub(r"\s+([)）])", r"\1", cleaned)
    cleaned = _EMPTY_PAREN.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip() or text


# 임베딩 모델 입력 길이를 고려한 검색어 상한.
SEARCH_QUERY_MAX_CHARS = 500

_CLOCK_QUESTION_RE = re.compile(
    r"(?:출근|퇴근|출퇴근).{0,16}(?:시간|시각|몇\s*시)"
    r"|(?:시간|시각|몇\s*시).{0,16}(?:출근|퇴근|출퇴근)"
)
_CLOCK_QUERY_EXPANSION = (
    "기본 근무시간 유연근무제 시차출퇴근제 "
    "A형 B형 C형 D형 E형 출근시간 퇴근시간"
)
_ANNUAL_LEAVE_COUNT_TERMS = ("며칠", "몇일", "일수", "사용가능", "쓸수", "최대")
_ANNUAL_LEAVE_QUERY_EXPANSION = "복무규정 연차휴가 사용 가능 일수 재직기간 출근율"

_FOLLOWUP_PREFIXES = (
    "그럼",
    "그러면",
    "그렇다면",
    "그경우",
    "이경우",
    "그건",
    "이건",
    "그것",
    "이것",
    "해당",
    "앞에서",
    "방금",
)


def _is_explicit_followup(message: str) -> bool:
    compact = re.sub(r"\s+", "", message or "")
    return any(compact.startswith(prefix) for prefix in _FOLLOWUP_PREFIXES)


def _active_clarification_parts(
    history: Sequence[HistoryTurn],
) -> tuple[list[str], str | None, list[str]]:
    """Reconstruct the latest unresolved deterministic clarification.

    WEB stores speaker/message only, so a multi-step reply has no explicit
    clarification id.  Starting from an ambiguous user turn, accept only
    subsequent user turns that fill a requested slot.  The most recently
    completed chain is also returned for an immediate ``그럼 ...`` follow-up.
    An unrelated new question clears both states, preventing old topics from
    being attached forever.
    """

    parts: list[str] = []
    code: str | None = None
    resolved_parts: list[str] = []
    for turn in history:
        if turn.speaker != "user" or not turn.message.strip():
            continue
        text = turn.message.strip()
        if code and is_clarification_reply(code, text):
            parts.append(text)
            decision = evaluate_clarification(" ".join(parts))
            if decision.needs_clarification:
                code = decision.code
                resolved_parts = []
            else:
                resolved_parts = list(parts)
                parts = []
                code = None
            continue

        decision = evaluate_clarification(text)
        if decision.needs_clarification:
            parts = [text]
            code = decision.code
            resolved_parts = []
        else:
            parts = []
            code = None
            resolved_parts = []
    return parts, code, resolved_parts


def _to_messages(
    req: ChatRequest, chunks: Sequence[RetrievedChunk], *, degraded: bool = False
) -> list[Message]:
    """대화 이력 + 이번 질문. 참고 문서는 마지막 사용자 턴에 붙인다.

    `degraded` 를 넘기는 이유: 문서가 0건일 때 '검색이 실패했다' 와 '검색은 됐는데
    관련 문서가 없다' 는 안내가 달라야 한다.
    """
    messages = [
        Message(role="assistant" if turn.speaker == "llm" else "user", content=turn.message)
        for turn in req.history
    ]
    context = build_answer_context(chunks, degraded=degraded)
    messages.append(Message(role="user", content=f"{context}\n\n[질문]\n{req.message}"))
    return messages


def build_search_query(message: str, history: Sequence[HistoryTurn] = ()) -> str:
    """RAG 에 보낼 검색어를 만든다.

    `history` 가 비어 있으면 질문 원문을 그대로 쓴다. 즉 WEB 이 대화 이력을
    보내지 않는 동안은 '질문을 각각 독립으로 취급'하는 동작이 된다.

    이력이 있어도 모든 직전 질문을 붙이지 않는다. 사용자가 새 주제로 넘어갔는데
    이전 질문까지 합치면 검색 자체가 오염되기 때문이다. ``그럼`` 같은 명시적
    후속 표현이나, 서버가 방금 요구한 확인 슬롯에 대한 답일 때만 직전 사용자
    질문을 앞에 붙인다. 임베딩 모델 입력 길이가 있으므로 전체 길이를 제한하되,
    **현재 질문은 절대 자르지 않고** 앞에 붙는 이전 질문 쪽을 줄인다.
    """
    message = message.strip()
    active_parts, active_code, resolved_parts = _active_clarification_parts(history)
    if active_code and is_clarification_reply(active_code, message):
        context = " ".join(active_parts)
        budget = SEARCH_QUERY_MAX_CHARS - len(message) - 1
        if budget <= 0:
            return message[:SEARCH_QUERY_MAX_CHARS]
        return f"{context[:budget]} {message}"

    previous = next(
        (t.message.strip() for t in reversed(history) if t.speaker == "user" and t.message.strip()),
        None,
    )
    if not previous:
        return message[:SEARCH_QUERY_MAX_CHARS]

    previous_decision = evaluate_clarification(previous)
    explicit_followup = _is_explicit_followup(message)
    carries_context = explicit_followup or (
        previous_decision.needs_clarification
        and is_clarification_reply(previous_decision.code, message)
    )
    if not carries_context:
        return message[:SEARCH_QUERY_MAX_CHARS]

    context = " ".join(resolved_parts) if explicit_followup and resolved_parts else previous
    budget = SEARCH_QUERY_MAX_CHARS - len(message) - 1
    if budget <= 0:
        return message[:SEARCH_QUERY_MAX_CHARS]
    return f"{context[:budget]} {message}"


def expand_retrieval_query(query: str) -> str:
    """짧은 생활형 질문을 해당 규정의 검색 표현으로 좁게 보강한다.

    사용자는 짧게 ``출근시간``이라고 물어도 통상 근무시간뿐 아니라 실제로 선택할
    수 있는 유연근무 시간대까지 기대한다. 일반 질의 전체에 키워드를 붙이면 검색을
    오염시키므로 출퇴근 *시각* 의도가 명확할 때만 좁게 확장한다. 연차 사용 일수는
    붙여쓰기 변형에서 연차수당이 앞서는 회귀를 막기 위해 복무규정의 연차휴가 기준
    표현을 보강하되, 질문에 ``수당``이 있으면 적용하지 않는다.
    """

    compact = " ".join((query or "").split())
    joined = re.sub(r"\s+", "", compact)
    expansions: list[str] = []
    if _CLOCK_QUESTION_RE.search(compact) and not all(
        term in compact for term in ("A형", "B형", "C형", "D형", "E형")
    ):
        expansions.append(_CLOCK_QUERY_EXPANSION)
    if (
        ("연차" in joined or "연가" in joined)
        and "수당" not in joined
        and any(term in joined for term in _ANNUAL_LEAVE_COUNT_TERMS)
    ):
        expansions.append(_ANNUAL_LEAVE_QUERY_EXPANSION)
    expanded = " ".join((compact, *expansions)).strip()
    return expanded[:SEARCH_QUERY_MAX_CHARS]


async def _retrieve(
    req: ChatRequest,
    query: str | None = None,
) -> tuple[list[RetrievedChunk], bool, int]:
    if not req.use_rag:
        return [], False, 0
    base_query = query or build_search_query(req.message, req.history)
    return await rag_client.search(expand_retrieval_query(base_query))


_RETRY_AFTER_RE = re.compile(r"retry in ([\d.]+)\s*s", re.I)


def _rate_limit_of(exc: Exception) -> ProviderRateLimited | None:
    """벤더의 429 를 알아본다.

    OpenAI(`openai.RateLimitError`)는 `.status_code`, Gemini(`google.genai` ClientError)는
    `.code` 로 상태를 노출한다. SDK 를 직접 import 하지 않고 속성으로 판별해,
    한쪽 SDK 가 없는 환경에서도 동작하게 한다.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status != 429:
        return None

    # Gemini 는 메시지에 "Please retry in 31.06s" 를 담아준다.
    m = _RETRY_AFTER_RE.search(str(exc))
    retry_after = float(m.group(1)) if m else None
    return ProviderRateLimited(retry_after=retry_after)


def _wrap_provider_error(exc: Exception) -> LLMServiceError:
    if isinstance(exc, LLMServiceError):
        return exc
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ProviderTimeout()
    rate_limited = _rate_limit_of(exc)
    if rate_limited is not None:
        logger.warning(
            "프로바이더 호출 한도 초과 (재시도 권장 %s초)", rate_limited.retry_after or "?"
        )
        return rate_limited
    logger.exception("프로바이더 호출 실패")
    return ProviderUnavailable()


async def generate_answer(req: ChatRequest) -> ChatResponse:
    settings = get_settings()
    started = time.perf_counter()
    effective_question = build_search_query(req.message, req.history)

    # 서로 다른 직군·제도에 서로 다른 규정이 적용되는 고위험 질문은 검색 결과나
    # 모델의 추측에 맡기지 않는다. 필요한 구분값만 먼저 묻고 다음 사용자 턴을
    # 기존 history+검색어 결합 로직으로 이어간다.
    # 직전 질문을 무조건 붙이지는 않는다. 사용자가 새 주제로 넘어가면 현재 문장만
    # 판정하고, "기술연구원이요" 같은 확인 슬롯 답이나 명시적 후속 질문일 때만
    # effective_question에 이전 질문이 결합된다.
    clarification = evaluate_clarification(effective_question)
    if clarification.needs_clarification:
        topic_by_code = {
            "parental_leave_employee_type": "휴가/휴직",
            "flexible_work_subtype": "근태/근무형태",
            "fixed_term_hire_category": "채용/임용",
            "holiday_pay_work_status": "급여/보수",
            "dui_discipline_event_details": "징계/행동강령",
        }
        topic = topic_by_code.get(clarification.code or "", FALLBACK_TOPIC)
        question = clarification.question or "적용 대상이나 상황을 조금 더 구체적으로 알려주세요."
        metrics.record_chat(
            "chat_clarification",
            chatroom_id=req.chatroom_id,
            topic=topic,
            rag_degraded=False,
            source_count=0,
            metrics=metrics.CallMetrics(
                provider="policy",
                model="deterministic",
                latency_ms=int((time.perf_counter() - started) * 1000),
                rag_ms=0,
            ),
        )
        return ChatResponse(
            answer=question,
            answer_status="clarification_required",
            clarification_question=question,
            topic=topic,
            sources=[],
            rag_degraded=False,
        )

    # 확인 질문의 짧은 답변은 원래 질문과 결합되어야 검색뿐 아니라 아래 의미
    # 검증도 같은 의도를 본다. 예: ``음주운전 징계?`` → ``초범·0.05%·무사고``.
    chunks, degraded, rag_ms = await _retrieve(req, effective_question)
    if degraded:
        answer = "지금은 규정 문서를 확인할 수 없습니다. 잠시 후 다시 시도해주세요."
        metrics.record_chat(
            "chat_rag_unavailable",
            chatroom_id=req.chatroom_id,
            topic=FALLBACK_TOPIC,
            rag_degraded=True,
            source_count=0,
            metrics=metrics.CallMetrics(
                provider="policy",
                model="deterministic",
                latency_ms=int((time.perf_counter() - started) * 1000),
                rag_ms=rag_ms,
            ),
        )
        return ChatResponse(
            answer=answer,
            answer_status="rag_unavailable",
            topic=FALLBACK_TOPIC,
            sources=[],
            rag_degraded=True,
        )

    provider = get_provider(req.provider)
    source_files = [c.original_file_name for c in chunks]

    # 답변 생성과 주제 분류는 동시에 시작하되, 보조 분류 지연/실패가 답변 생성과
    # 근거 교정의 15초 예산을 소모하거나 전체 요청을 실패시키지 않게 분리한다.
    messages = _to_messages(req, chunks, degraded=degraded)
    llm_started = time.perf_counter()
    topic_task = asyncio.create_task(
        classify(effective_question, source_files, req.provider)
    )
    try:
        answer_result = await asyncio.wait_for(
            provider.generate(
                system=ANSWER_SYSTEM,
                messages=messages,
                temperature=0,
                max_tokens=settings.answer_max_tokens,
            ),
            timeout=settings.llm_timeout_sec,
        )
    except Exception as exc:
        topic_task.cancel()
        err = _wrap_provider_error(exc)
        # 실패도 기록해야 성능 보고서에서 에러율/타임아웃 비율을 낼 수 있다.
        metrics.record_error(
            "chat_error",
            chatroom_id=req.chatroom_id,
            error_code=err.error_code,
            provider=provider.name,
            model=provider.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            rag_ms=rag_ms,
        )
        raise err from exc

    # 1차로 상태/근거 ID/수치 완전 일치를 결정적으로 검사한다. 급여·휴직·징계처럼
    # 조건과 표 범위가 중요한 질문은 enum 제약 감사 호출로 의미적 누락도 확인한다.
    grounded: GroundingResult = validate_answer(answer_result.text, chunks, degraded=False)
    prompt_tokens = answer_result.prompt_tokens
    completion_tokens = answer_result.completion_tokens
    repaired_once = False
    semantic_verdict: str | None = None

    async def verify_semantics(raw_answer: str, result: GroundingResult) -> bool:
        nonlocal semantic_verdict
        mode = getattr(settings, "answer_verify_mode", "risky")
        # 모델이 [E번호] 형식을 빠뜨렸다면 질문 종류와 무관하게 의미 검증한다.
        # 형식 누락만으로 정상 답변을 버리지는 않되, 근거 없는 주장을 느슨하게
        # 통과시키지도 않는다.
        required = (
            result.implicit_evidence
            or should_verify(effective_question, result.status, mode)
        ) and bool(chunks)
        if not required:
            semantic_verdict = "SKIPPED"
            return True

        remaining = settings.llm_timeout_sec - (time.perf_counter() - llm_started)
        if remaining < 0.5:
            semantic_verdict = "TIME_BUDGET_EXHAUSTED"
            return False
        try:
            verdict = await asyncio.wait_for(
                provider.classify(
                    system=VERIFIER_SYSTEM,
                    user_content=build_verifier_input(
                        question=effective_question,
                        raw_answer=raw_answer,
                        chunks=chunks,
                        evidence_numbers=result.evidence_numbers,
                        status=result.status,
                    ),
                    allowed=("SUPPORTED", "UNSUPPORTED"),
                ),
                timeout=remaining,
            )
        except Exception as exc:
            logger.warning("의미적 근거 검증 실패 — 안전 응답으로 대체합니다: %s", exc)
            semantic_verdict = "VERIFIER_ERROR"
            return False
        semantic_verdict = verdict if verdict in {"SUPPORTED", "UNSUPPORTED"} else "INVALID"
        return semantic_verdict == "SUPPORTED"

    semantic_ok = grounded.valid and await verify_semantics(answer_result.text, grounded)
    first_errors = list(grounded.errors)
    if grounded.valid and not semantic_ok:
        first_errors.append("답변의 주장·적용 대상·조건·범위가 인용 근거와 완전히 일치하지 않습니다")

    # 형식 또는 의미 검증에 실패한 초안만 남은 전체 예산 안에서 한 번 교정한다.
    if not grounded.valid or not semantic_ok:
        remaining = settings.llm_timeout_sec - (time.perf_counter() - llm_started)
        if remaining >= 1.0:
            try:
                repaired_once = True
                repaired = await asyncio.wait_for(
                    provider.generate(
                        system=ANSWER_SYSTEM,
                        messages=[
                            *messages,
                            Message(role="assistant", content=answer_result.text),
                            Message(role="user", content=repair_instruction(first_errors)),
                        ],
                        temperature=0,
                        max_tokens=settings.answer_max_tokens,
                    ),
                    timeout=remaining,
                )
                if prompt_tokens is not None and repaired.prompt_tokens is not None:
                    prompt_tokens += repaired.prompt_tokens
                else:
                    prompt_tokens = prompt_tokens or repaired.prompt_tokens
                if completion_tokens is not None and repaired.completion_tokens is not None:
                    completion_tokens += repaired.completion_tokens
                else:
                    completion_tokens = completion_tokens or repaired.completion_tokens

                grounded = validate_answer(repaired.text, chunks, degraded=False)
                semantic_ok = grounded.valid and await verify_semantics(repaired.text, grounded)
                answer_result = repaired
            except Exception as exc:
                logger.warning("답변 근거 교정 실패 — 안전 응답으로 대체합니다: %s", exc)
                semantic_ok = False

    safe_to_return = grounded.valid and semantic_ok
    # 답변 일부가 로그에 남지 않도록 오류 종류만 기록한다.
    metrics.record(
        "answer_grounding_validation",
        chatroom_id=req.chatroom_id,
        passed=safe_to_return,
        repaired=repaired_once,
        semantic_verdict=semantic_verdict,
        implicit_evidence=grounded.implicit_evidence,
        error_codes=[error.split(":", 1)[0] for error in grounded.errors],
    )

    # 주제 분류는 여기까지 백그라운드에서 충분히 실행됐다. 아직 끝나지 않았으면
    # 최대 0.5초만 기다리고 기타로 대체한다.
    try:
        if topic_task.done():
            topic, _ = await topic_task
        else:
            remaining = settings.llm_timeout_sec - (time.perf_counter() - llm_started)
            if remaining <= 0:
                raise asyncio.TimeoutError
            topic, _ = await asyncio.wait_for(topic_task, timeout=min(0.5, remaining))
    except Exception:
        topic_task.cancel()
        topic = FALLBACK_TOPIC

    if safe_to_return:
        answer_status = {
            "ANSWER": "answered",
            "CLARIFY": "clarification_required",
            "NOT_FOUND": "not_found",
            "RAG_UNAVAILABLE": "rag_unavailable",
        }[grounded.status]
        if grounded.status == "ANSWER":
            final_answer = strip_unverifiable_citations(
                grounded.text,
                "\n".join(c.content for c in chunks),
                allow=settings.answer_cite_articles,
            )
            used_chunks = [chunks[number - 1] for number in grounded.evidence_numbers]
        elif grounded.status == "CLARIFY":
            final_answer = grounded.text
            used_chunks = []
        elif grounded.status == "NOT_FOUND":
            final_answer = (
                "제공된 규정 문서에서 해당 내용을 찾을 수 없습니다. "
                "인사·복무 관련 사항이라면 인사팀에 문의해주세요."
            )
            used_chunks = []
        else:  # 정상 RAG 경로에서는 validator가 RAG_UNAVAILABLE을 거부한다.
            final_answer = "지금은 규정 문서를 확인할 수 없습니다. 잠시 후 다시 시도해주세요."
            used_chunks = []
    else:
        answer_status = "verification_failed"
        final_answer = (
            "답변에 필요한 근거를 충분히 검증하지 못했습니다. "
            "질문을 조금 더 구체적으로 작성하거나 인사팀에 문의해주세요."
        )
        used_chunks = []

    source_chunks = rag_client.unique_source_chunks(used_chunks)

    # 계측값은 응답에 넣지 않고 로그로만 남긴다.
    metrics.record_chat(
        "chat",
        chatroom_id=req.chatroom_id,
        topic=topic,
        rag_degraded=degraded,
        source_count=len(chunks),
        source_files=source_files,
        metrics=metrics.CallMetrics(
            provider=provider.name,
            model=answer_result.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            rag_ms=rag_ms,
        ),
    )

    return ChatResponse(
        answer=final_answer,
        answer_status=answer_status,
        clarification_question=(
            final_answer if answer_status == "clarification_required" else None
        ),
        topic=topic[:TOPIC_MAX_LEN],
        sources=[c.to_source() for c in source_chunks],
        rag_degraded=degraded,
    )


async def stream_answer(req: ChatRequest) -> AsyncIterator[tuple[str, dict]]:
    """검증 완료된 답변을 SSE 형태로 내보낸다.

    이 라우트는 현재 WEB에서 사용하지 않는다. 근거 검증 전에 토큰을 먼저 내보내면
    잘못된 급여·징계 안내를 되돌릴 수 없으므로, 안전 경로에서는 완성본을 버퍼링한
    뒤 한 토큰 이벤트로 전달한다.
    """
    try:
        response = await generate_answer(req)
    except LLMServiceError as err:
        yield "error", {"error_code": err.error_code, "message": err.message}
        return

    yield "sources", {
        "sources": [source.model_dump() for source in response.sources],
        "rag_degraded": response.rag_degraded,
    }
    yield "token", {"delta": response.answer}
    yield "done", {
        "topic": response.topic,
        "answer_status": response.answer_status,
        "clarification_question": response.clarification_question,
    }
