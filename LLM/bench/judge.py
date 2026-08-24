"""답변이 근거 문서에 실제로 뒷받침되는지 채점한다 (LLM-as-judge).

    python bench/judge.py                      # 가장 최근 결과
    python bench/judge.py --tag e2e            # 특정 조건
    python bench/judge.py --file bench/results/....jsonl

왜 필요한가
-----------
`run_bench.py` 는 주제 정확도·검색 recall·조문 인용을 기계적으로 재지만,
**답변 내용이 근거에 있는지**는 못 잰다. 그래서 이런 답변을 통과시켰다.

    질문   연차 사용방법에 대해 알려줘
    근거   근로기준법 p.14, 복무규정 제20조의2 (둘 다 '사용촉진' 조항)
    답변   "연차 유급휴가는 사전에 신청하여 사용해야 하며, 사용 시에는
            상급자의 승인을 받아야 합니다"

'사전 신청·상급자 승인' 은 근거 어디에도 없다. 복무규정 전체를 뒤져도 연차에
그런 조항은 없다(조퇴·외출은 제13조에 있지만 연차와 다르다). 주제만 맞는 문서가
들어오니 모델이 "연차 얘기가 있으니 아는 대로 써도 된다" 고 판단한 것이다.

규정 안내 서비스에서 이런 실패가 가장 위험하다. 실무적으로 그럴듯해서 틀린 티가
안 나고, 직원이 그대로 믿는다.

왜 규칙 기반이 아니라 LLM 인가
------------------------------
어휘 겹침으로 재려 했지만 한국어에서 잘 안 된다. 조사·어미 변화가 심하고,
같은 뜻을 다른 말로 쓰면(문서 "가산휴가" / 답변 "추가 휴가") 겹침이 안 잡힌다.
반대로 "신청" 같은 흔한 단어는 무관한 맥락에서도 겹쳐 오탐이 난다.

여기서 필요한 것은 '이 문장이 저 근거에서 나올 수 있는가' 라는 판단이라
LLM 이 맞다. **측정 도구라서** 비용과 지연이 서비스에 영향을 주지 않는다.

채점자를 신뢰할 수 있는가
-------------------------
판정 대상(gpt-4o-mini)보다 강한 모델을 쓰고, 판정 근거로 **문제 문장을 그대로
인용**하게 한다. 인용이 답변에 실제로 없으면 그 판정은 버린다 — 채점자가
지어낸 것이므로. 최종 수치는 사람이 표본 검수한 뒤 보고서에 싣는다.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import sys
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parent))

RESULTS_DIR = BENCH_DIR / "results"

# 채점자는 판정 대상보다 강한 모델을 쓴다. 같은 모델로 자기 답을 채점하면
# 자기가 놓친 것을 똑같이 놓친다.
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-4.1")

JUDGE_SYSTEM = """당신은 사내 규정 안내 챗봇의 답변을 검수합니다.

[근거]에 들어 있는 내용만으로 [답변]의 각 문장이 뒷받침되는지 판정하세요.

**찾으려는 것은 근거에 없는 새로운 사실입니다.** 문장이 어색하거나 군더더기라는
이유로 잡지 마세요. 애매하면 문제없다고 판정하세요.

문제로 잡을 것 (근거에 없는데 새로 만들어낸 것):
- 수치·기간·비율 ("3개월 평균임금", "10일 이내", "최대 25일")
- 절차·요건 ("사전에 신청해야", "상급자의 승인을 받아야", "~에게 신고해야")
- 조문 번호, 규정 이름, 기관 이름
- 근거에 없는 규정의 내용을 아는 것처럼 서술한 것

문제로 잡지 말 것:
- 근거 내용을 다른 말로 바꿔 쓴 것
  (근거 "가산휴가" → 답변 "추가로 부여되는 휴가")
- 근거에서 자연스럽게 따라오는 요약·정리·결론
  ("따라서 시험을 봐야 할 수도 있습니다", "이러한 기준을 충족해야 합니다")
- 새로운 사실이 없는 도입·연결 문장
  ("다음과 같은 기준을 따라야 합니다", "이와 같이 규정되어 있습니다")
- 안내 문구 ("인사팀에 문의하세요", "규정에서 찾을 수 없습니다")
- 근거가 비어 있고 답변이 안내 문구뿐인 경우

판정이 갈릴 때 기준: **그 문장을 읽은 직원이 잘못된 행동을 하게 되는가.**
그렇다면 문제로 잡고, 아니면 넘어가세요.

출력은 JSON 하나로만 하세요.
{"unsupported": ["답변에서 그대로 복사한 문제 문장", ...]}

문제가 없으면 빈 배열을 주세요. 문장은 **답변에 있는 그대로** 복사하세요.
요약하거나 바꿔 쓰지 마세요."""


def _pick_file(args: argparse.Namespace) -> Path:
    if args.file:
        return Path(args.file)
    pattern = f"*_{args.tag}_*.jsonl" if args.tag else "*.jsonl"
    files = sorted(RESULTS_DIR.glob(pattern))
    if not files:
        raise SystemExit(f"결과 파일이 없습니다: {RESULTS_DIR / pattern}")
    return files[-1]


async def _judge_one(client, row: dict) -> list[str]:
    answer = row.get("answer") or ""
    if not answer:
        return []

    response = await client.chat.completions.create(
        model=JUDGE_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"[질문]\n{row['question']}\n\n"
                    f"[근거]\n{row.get('context') or '(없음)'}\n\n"
                    f"[답변]\n{answer}"
                ),
            },
        ],
    )
    parsed = json.loads(response.choices[0].message.content or "{}")
    claims = parsed.get("unsupported") or []

    # 채점자가 지어낸 인용은 버린다. 답변에 실제로 없는 문장을 문제 삼았다면
    # 그 판정 자체를 믿을 수 없다.
    normalized = answer.replace(" ", "")
    return [c for c in claims if isinstance(c, str) and c.replace(" ", "") in normalized]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="")
    ap.add_argument("--tag", default="", help="이 태그의 가장 최근 실행을 채점한다")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    path = _pick_file(args)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if args.limit:
        rows = rows[: args.limit]

    if "context" not in rows[0]:
        raise SystemExit(
            f"{path.name} 에 context 가 없습니다. run_bench.py 를 다시 돌려 주세요.\n"
            "(근거 본문을 기록하기 시작한 것보다 오래된 결과 파일입니다)"
        )

    from app.config import get_settings
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=get_settings().openai_api_key)

    print(f"채점 {path.name} · {len(rows)}문항 · 채점자 {JUDGE_MODEL}\n")

    flagged: list[tuple[dict, list[str]]] = []
    for i, row in enumerate(rows, 1):
        try:
            claims = await _judge_one(client, row)
        except Exception as exc:  # 채점 실패가 전체를 막지 않게 한다
            print(f"  [{i:2d}/{len(rows)}] 채점 실패 {row['question_id']}: {exc}")
            continue
        if claims:
            flagged.append((row, claims))
        print(f"  [{i:2d}/{len(rows)}] {'X ' if claims else 'OK'} {row['question_id']}")

    print(f"\n근거 없는 주장이 있는 답변 {len(flagged)}/{len(rows)}\n")
    for row, claims in flagged:
        print(f"[{row['question_id']}] {row['question']}")
        print(f"   근거 문서: {sorted({s.split(' p.')[0] for s in row['got_sources']}) or '(없음)'}")
        for c in claims:
            print(f"   ✗ {c}")
        print()

    out = path.with_name(path.stem + "_judged.json")
    out.write_text(
        json.dumps(
            {
                "source": path.name,
                "judge_model": JUDGE_MODEL,
                "total": len(rows),
                "flagged": len(flagged),
                "items": [
                    {"question_id": r["question_id"], "unsupported": c} for r, c in flagged
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
