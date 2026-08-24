"""근거 없는 주장이 **코퍼스 어딘가에는 있는지** 추적한다.

    python bench/trace_claim.py --tag article-head

`judge.py` 는 답변을 **프롬프트에 들어간 근거**하고만 대조한다. 그래서 "근거 없음"
판정이 두 가지를 뭉뚱그린다.

  (a) 코퍼스에는 있는데 검색이 못 찾아왔다   → RAG 검색 문제
  (b) 코퍼스 어디에도 없다                 → LLM 이 지어낸 것

고쳐야 할 곳이 완전히 다르므로 갈라야 한다. 여기서는 지적된 문장마다 **28개 문서
전체**(사내 규정 + 법령)를 뒤져 뒷받침할 만한 대목이 있는지 찾는다.

검색은 `corpus.py` 를 쓰되 파일 제한 없이 전체를 대상으로 한다. 후보를 뽑은 뒤
판정은 `judge.py` 와 같은 방식으로 LLM 에게 맡긴다 — 한국어에서 어휘 겹침으로는
같은 뜻 다른 표현을 못 잡기 때문이다.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parent))
sys.path.insert(0, str(BENCH_DIR))

RESULTS_DIR = BENCH_DIR / "results"
JUDGE_MODEL = "gpt-4.1"

TRACE_SYSTEM = """당신은 사내 규정 문서에서 어떤 주장의 근거를 찾는 일을 합니다.

[주장]이 [문서 발췌] 중 하나로 뒷받침되는지 판정하세요.

- 표현이 달라도 같은 내용이면 뒷받침됩니다.
- 주장의 핵심(수치·기간·절차·요건)이 발췌에 없으면 뒷받침되지 않습니다.
- 비슷한 주제를 다룰 뿐 그 내용이 없으면 뒷받침되지 않습니다.

출력은 JSON 하나로만 하세요.
{"supported": true/false, "where": "근거가 된 문서명과 대목 (없으면 빈 문자열)"}"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="article-head")
    ap.add_argument("--top-k", type=int, default=8, help="주장마다 뒤질 후보 청크 수")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    judged = sorted(glob.glob(str(RESULTS_DIR / f"*_{args.tag}_*_judged.json")))
    if not judged:
        raise SystemExit(f"채점 결과가 없습니다. 먼저 judge.py --tag {args.tag} 를 돌리세요.")
    data = json.load(open(judged[-1], encoding="utf-8"))

    import corpus

    loaded = corpus.load_corpus()
    all_files = list(loaded)
    print(f"코퍼스 {len(all_files)}개 문서 · 지적된 주장 "
          f"{sum(len(i['unsupported']) for i in data['items'])}개\n")

    from app.config import get_settings
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=get_settings().openai_api_key)

    in_corpus: list[tuple[str, str, str]] = []
    not_in_corpus: list[tuple[str, str]] = []

    for item in data["items"]:
        qid = item["question_id"]
        for claim in item["unsupported"]:
            # 파일 제한 없이 전체에서 후보를 뽑는다.
            chunks = corpus.search(claim, all_files, top_k=args.top_k, corpus=loaded)
            excerpt = "\n\n".join(
                f"[{c.original_file_name} p.{c.page}]\n{c.content}" for c in chunks
            )
            try:
                resp = await client.chat.completions.create(
                    model=JUDGE_MODEL,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": TRACE_SYSTEM},
                        {"role": "user", "content": f"[주장]\n{claim}\n\n[문서 발췌]\n{excerpt}"},
                    ],
                )
                parsed = json.loads(resp.choices[0].message.content or "{}")
            except Exception as exc:
                print(f"  판정 실패 {qid}: {exc}")
                continue

            if parsed.get("supported"):
                in_corpus.append((qid, claim, parsed.get("where", "")))
            else:
                not_in_corpus.append((qid, claim))
            print(f"  {'있음' if parsed.get('supported') else '없음'}  [{qid}] {claim[:60]}")

    total = len(in_corpus) + len(not_in_corpus)
    print(f"\n{'=' * 60}")
    print(f"코퍼스에 있는데 검색이 못 찾아온 것  {len(in_corpus)}/{total}  → RAG 검색 문제")
    print(f"코퍼스 어디에도 없는 것              {len(not_in_corpus)}/{total}  → LLM 환각")
    print(f"{'=' * 60}\n")

    print("### 코퍼스 어디에도 없는 것 (LLM 이 지어낸 것)")
    for qid, claim in not_in_corpus:
        print(f"  [{qid}] {claim}")
    print()
    print("### 코퍼스에는 있는데 검색이 놓친 것")
    for qid, claim, where in in_corpus:
        print(f"  [{qid}] {claim[:70]}")
        print(f"       → {where[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
