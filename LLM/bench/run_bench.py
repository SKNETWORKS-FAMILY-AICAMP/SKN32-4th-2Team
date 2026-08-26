"""성능 측정 실행기.

`questions.yaml` 34문항을 실제 서비스 경로(`generate_answer`)로 돌려 결과를
JSONL 로 남긴다. 집계와 보고서 작성은 `report.py` 가 맡는다.

    python bench/run_bench.py --provider openai                    # baseline
    python bench/run_bench.py --provider openai --variant catdef   # 프롬프트 변형
    python bench/run_bench.py --provider gemini --rpm 8            # 무료 티어 한도

검색은 실제 RAG 가 아니라 `corpus.py` 를 쓴다
-------------------------------------------
질문별 정답 문서가 이미 라벨링되어 있으므로, 그 문서 안에서만 관련 구간을 찾는다.
즉 **검색이 완벽하다고 가정**한 상태에서 LLM 성능만 잰다.
실제 RAG 는 검색에 30초가 걸려 34문항 한 조건에 17분이라 튜닝 루프를 돌릴 수 없다.

여기서 나온 점수는 end-to-end 성능이 아니라 **LLM 쪽 상한선**이다.
나중에 실제 RAG 로 같은 문항을 돌린 점수와의 차이가 검색이 깎아먹은 몫이다.

왜 HTTP 가 아니라 함수를 직접 부르는가
-----------------------------------
프롬프트 변형을 비교하려면 조건마다 서버를 재시작해야 하는데, 그러면 프로바이더
예열 비용을 매번 다시 문다. 같은 프로세스 안에서 부르면 조건만 바꿔 연속으로
돌릴 수 있다. HTTP 계층 오버헤드는 수 ms 라 비교에 영향이 없다.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parent))
sys.path.insert(0, str(BENCH_DIR))

QUESTIONS = BENCH_DIR / "questions.yaml"
RESULTS_DIR = BENCH_DIR / "results"

# 지금 처리 중인 문항의 정답 문서. 패치된 검색 함수가 읽는다.
# 전역 변수 대신 contextvar 를 쓰는 이유: 나중에 동시 실행으로 바꿔도 안 깨진다.
_current_sources: contextvars.ContextVar[list[str]] = contextvars.ContextVar(
    "current_sources", default=[]
)


def _install_corpus_retrieval(top_k: int) -> None:
    """`rag_client.search` 를 로컬 코퍼스 검색으로 바꿔 끼운다.

    `answer.py` 는 `rag_client.search` 를 이름으로 참조하므로 모듈 속성을 갈아끼우면
    호출 경로 전체가 바뀐다. 서비스 코드는 손대지 않는다.
    """
    import corpus

    from app.services import rag_client

    loaded = corpus.load_corpus()

    async def _search(query: str, k: int | None = None):
        started = time.perf_counter()
        chunks = corpus.search(
            query, _current_sources.get(), top_k=k or top_k, corpus=loaded
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        # out_of_scope 문항은 정답 문서가 없어 빈 목록이 정상이다.
        # 검색 실패(degraded)가 아니므로 False 로 둔다.
        return chunks, False, elapsed

    rag_client.search = _search  # type: ignore[assignment]


# 답변이 인용한 조문이 실제로 근거 문서 안에 있었는지 보려면 청크 **본문**이
# 필요하다. API 응답에는 본문이 안 나가므로(파일명·페이지만) 검색 함수를 한 겹
# 감싸 본문을 붙잡아 둔다.
_ARTICLE = re.compile(r"제\s?\d+조(?:의\s?\d+)?")
# 조 번호 없이 항·호만 대는 인용. "근로기준법 제2항에 명시되어 있습니다" 처럼
# 쓰면 법령에서 그런 식으로 특정할 수 없어 확인이 불가능하다. 청크가 조문
# 중간부터 시작해 조 번호가 안 보일 때 모델이 주워 쓴다.
#
# "별지 제1호 서식" 은 제외한다. 서식 번호이지 조문 인용이 아니다
# (시간선택제 전환 신청서 안내에서 걸려 오탐이 났다).
_BARE_CLAUSE = re.compile(r"(?<!별지 )(?<!별표 )제\s?\d+[항호](?!\s*서식)")
_last_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "last_context", default=""
)


def _wrap_search_to_capture() -> None:
    from app.services import rag_client

    original = rag_client.search

    async def _capturing(query: str, k: int | None = None):
        chunks, degraded, ms = await original(query, k)
        _last_context.set("\n".join(c.content for c in chunks))
        return chunks, degraded, ms

    rag_client.search = _capturing  # type: ignore[assignment]


def _citation_check(answer: str | None) -> tuple[list[str], list[str]]:
    """답변이 든 조문 번호 중 근거 문서에 없는 것을 골라낸다.

    규정 안내 서비스에서 잘못된 조문 인용은 내용이 맞아도 신뢰를 깎는다.
    실제로 "휴일근로 100분의 50 가산"(제56조)을 설명하며 제55조·제57조를
    대는 일이 있었다. 근거 문서가 조문 중간부터 시작해 조 번호가 안 보이면
    모델이 기억으로 번호를 붙이기 때문이다.
    """
    if not answer:
        return [], []
    context = _last_context.get()
    cited = sorted({m.replace(" ", "") for m in _ARTICLE.findall(answer)})
    in_context = {m.replace(" ", "") for m in _ARTICLE.findall(context)}
    bad = [c for c in cited if c not in in_context]

    # 조 번호 없이 항·호만 댄 것도 잘못된 인용이다. 답변에 `제N조` 가 하나도
    # 없는데 `제N항` 이 나오면 그렇게 본다.
    if not cited:
        bad += [m.replace(" ", "") for m in _BARE_CLAUSE.findall(answer)]
    return cited, sorted(set(bad))


async def _run_one(question: dict, provider: str, top_k: int) -> dict:
    from app.errors import LLMServiceError
    from app.schemas import ChatRequest
    from app.services.answer import generate_answer

    _current_sources.set(question.get("sources") or [])

    req = ChatRequest(
        chatroom_id=f"bench-{question['id']}",
        message=question["question"],
        provider=provider,
    )

    started = time.perf_counter()
    error_code = None
    res = None
    try:
        res = await generate_answer(req)
    except LLMServiceError as exc:
        error_code = exc.error_code
    latency_ms = int((time.perf_counter() - started) * 1000)

    cited, bad = _citation_check(res.answer if res else None)

    expected_sources = question.get("sources") or []
    # 파일명만 담으면 같은 문서의 다른 페이지가 중복처럼 보인다.
    # recall 판정은 파일명 집합으로 하고, 기록은 페이지까지 남긴다.
    got_files = [s.original_file_name for s in res.sources] if res else []
    got_sources = (
        [f"{s.original_file_name} p.{s.page}" for s in res.sources] if res else []
    )
    expected_action = question.get("expected_action")
    expected_statuses = {
        "clarify": {"clarification_required"},
        # 직접 근거가 검색됐으면 답하고, 검색되지 않았으면 근거 없이 채우지 않는
        # not_found도 안전한 동작이다. 내용 정답 여부는 별도 수기/심판 평가 대상이다.
        "answer_if_direct_evidence_else_not_found": {"answered", "not_found"},
    }.get(expected_action)
    got_status = res.answer_status if res else None

    return {
        "question_id": question["id"],
        "group": question.get("group"),
        "question": question["question"],
        "out_of_scope": bool(question.get("out_of_scope")),
        "severity": question.get("severity"),
        "expected_action": expected_action,
        "answer_status": got_status,
        "action_correct": (got_status in expected_statuses) if expected_statuses else None,
        "clarification_question": res.clarification_question if res else None,
        "expected_topic": question["category"],
        "got_topic": res.topic if res else None,
        "topic_correct": bool(res and res.topic == question["category"]),
        "expected_sources": expected_sources,
        "got_sources": got_sources,
        "source_count": len(got_sources),
        # 정답 문서가 하나라도 검색됐는가. 지금은 정답 문서 안에서만 찾으므로
        # 거의 항상 참이다 — 실제 RAG 를 붙였을 때 의미가 생기는 지표다.
        "source_recall": bool(set(expected_sources) & set(got_files))
        if expected_sources
        else None,
        "answer": res.answer if res else None,
        "answer_chars": len(res.answer) if res else 0,
        "cited_articles": cited,
        # 근거 문서에 없는 조문을 든 것. 내용이 맞아도 신뢰를 깎는다.
        "bad_citations": bad,
        # 프롬프트에 실제로 들어간 근거 본문. judge.py 가 답변과 대조한다.
        # 파일이 커지지만 results/ 는 .gitignore 대상이라 상관없다.
        "context": _last_context.get(),
        "rag_degraded": bool(res.rag_degraded) if res else None,
        "latency_ms": latency_ms,
        "error_code": error_code,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["openai", "gemini", "qwen"])
    ap.add_argument("--tag", default="", help="조건 이름. 비우면 --variant 값을 쓴다")
    ap.add_argument(
        "--variant", default="baseline", help="프롬프트 변형. variants.py 참고"
    )
    ap.add_argument(
        "--model",
        default="",
        help="모델 이름을 덮어쓴다. 비우면 .env 값. 기록된 JSONL 의 model 필드로 남는다",
    )
    ap.add_argument(
        "--retrieval",
        default="corpus",
        choices=["corpus", "rag"],
        help="corpus=정답 문서 안에서만 검색(LLM 상한선) · rag=실제 RAG 서비스(end-to-end)",
    )
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--rpm", type=int, default=0, help="분당 요청 상한. 0이면 제한 없음")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 N개만 (빠른 확인용)")
    ap.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="서비스와 동일한 LLM 타임아웃(초). 장시간 계측은 명시적으로 늘립니다",
    )
    args = ap.parse_args()
    tag = args.tag or args.variant

    # 설정은 lru_cache 라 첫 참조 전에 넣어야 한다.
    # 기본값은 운영과 같은 15초로 회귀를 잡는다. 제한 없이 지연 분포를 볼 때만
    # --timeout 값을 명시적으로 늘린다.
    os.environ["LLM_TIMEOUT_SEC"] = str(args.timeout)
    os.environ["LLM_MODE"] = "live"
    if args.model:
        # 환경변수가 .env 보다 우선한다(pydantic-settings 기본 동작).
        os.environ[f"{args.provider.upper()}_MODEL"] = args.model

    from app.config import get_settings
    from app.providers import registry
    from app.services import topic as topic_service

    get_settings.cache_clear()
    if args.retrieval == "corpus":
        _install_corpus_retrieval(args.top_k)
    else:
        # 실제 RAG 를 쓴다. 서비스 코드를 그대로 통과하므로 아무것도 갈아끼우지 않는다.
        # CPU FAISS도 같은 기준으로 검증하도록 운영 기본값과 일치시킨다.
        os.environ["RAG_MODE"] = "live"
        os.environ.setdefault("RAG_TIMEOUT_SEC", "45")
        os.environ["RAG_TOP_K"] = str(args.top_k)
        get_settings.cache_clear()
    _wrap_search_to_capture()

    # 프롬프트 변형은 서비스 모듈이 임포트된 **뒤**에 적용해야 한다.
    # (소비처의 모듈 속성을 갈아끼우는 방식이라 대상이 먼저 있어야 한다)
    import variants

    variants.check_categories()
    applied = variants.apply(args.variant)

    # 같은 질문을 다시 돌릴 때 캐시가 응답하면 지연이 0으로 찍혀 분포가 망가진다.
    topic_service.clear_cache()

    registry.warm_up()
    await registry.preconnect_all()
    provider = registry.get_provider(args.provider)

    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.limit:
        questions = questions[: args.limit]

    limiter = None
    if args.rpm:
        from throttle import RateLimiter

        limiter = RateLimiter(rpm=args.rpm)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{run_id}_{tag}_{args.provider}.jsonl"

    print(f"조건 {tag} · {args.provider}/{provider.model} · {len(questions)}문항")
    if applied:
        print(f"프롬프트 변형 {args.variant}: {', '.join(applied)} 교체")
    print(f"결과 → {out_path}\n")

    started_all = time.perf_counter()
    with out_path.open("w", encoding="utf-8") as f:
        for i, q in enumerate(questions, 1):
            if limiter:
                waited = await limiter.acquire()
                if waited:
                    print(f"    (한도 대기 {waited:.0f}s)")

            row = await _run_one(q, args.provider, args.top_k)
            row.update(
                {
                    "ts": datetime.now().astimezone().isoformat(),
                    "run_id": run_id,
                    "tag": tag,
                    "variant": args.variant,
                    "provider": args.provider,
                    "model": provider.model,
                    "top_k": args.top_k,
                    "retrieval": args.retrieval,
                }
            )
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()  # 중간에 끊겨도 여기까지는 남는다

            mark = "OK " if row["topic_correct"] else "X  "
            if row["error_code"]:
                mark = "ERR"
            print(
                f"  [{i:2d}/{len(questions)}] {mark} {row['question_id']:28s} "
                f"{str(row['got_topic']):12s} {row['latency_ms']:>6}ms"
                + (f"  {row['error_code']}" if row["error_code"] else "")
            )

    print(f"\n완료 {time.perf_counter() - started_all:.0f}s → {out_path}")
    print("집계: python bench/report.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
