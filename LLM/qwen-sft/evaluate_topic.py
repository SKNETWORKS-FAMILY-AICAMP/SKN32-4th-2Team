"""SFT 적용 전후의 HR 주제 분류 회귀를 34문항으로 사전 점검한다."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from dotenv import load_dotenv

EARLY_ROOT = Path(__file__).resolve().parent
load_dotenv(EARLY_ROOT / ".env")

from src.io_utils import read_jsonl, write_json, write_jsonl
from src.model_utils import generate, load_inference_model
from src.settings import ROOT, SETTINGS

CATEGORIES = [
    "휴가/휴직",
    "근태/근무형태",
    "급여/보수",
    "채용/임용",
    "인사/승진",
    "복리후생",
    "복무/징계",
    "기타",
]


def parse_topic(text: str) -> str | None:
    cleaned = re.sub(r"[`\"'\s]", "", text)
    exact = [category for category in CATEGORIES if cleaned == category]
    if exact:
        return exact[0]
    mentioned = [category for category in CATEGORIES if category in text]
    return mentioned[0] if len(mentioned) == 1 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True, choices=["base", "sft"])
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    holdout = read_jsonl(SETTINGS.holdout_file)
    if args.limit:
        holdout = holdout[: args.limit]
    model, tokenizer = load_inference_model(args.variant)
    results = []
    for index, row in enumerate(holdout):
        raw = generate(
            model,
            tokenizer,
            row["topic_messages"],
            SETTINGS.seed + index,
            max_new_tokens=32,
            do_sample=False,
        )
        got = parse_topic(raw)
        results.append(
            {
                "variant": args.variant,
                "question_id": row["id"],
                "question": row["question"],
                "expected_topic": row["expected_topic"],
                "raw_output": raw,
                "got_topic": got,
                "correct": got == row["expected_topic"],
            }
        )
        print(
            f"[{index + 1:02d}/{len(holdout)}] {row['id']} "
            f"expected={row['expected_topic']} got={got or '<parse-fail>'}"
        )

    correct = sum(row["correct"] for row in results)
    canonical = bool(not args.limit and len(holdout) == 34)
    summary = {
        "variant": args.variant,
        "questions": len(holdout),
        "correct": correct,
        "accuracy": correct / len(holdout) if holdout else 0,
        "parse_failures": sum(row["got_topic"] is None for row in results),
        "canonical_run": canonical,
        "precheck_gate_at_least_32_of_34": canonical and correct >= 32,
        "note": (
            "이 검사는 Hugging Face 직접 생성 사전 점검입니다. 최종 채택은 "
            "Ollama JSON Schema enum 제약을 적용한 기존 팀 벤치로 다시 확인합니다."
        ),
    }
    suffix = args.variant if canonical else f"{args.variant}_smoke_{len(holdout)}q"
    report_dir = ROOT / "reports"
    write_jsonl(report_dir / f"topic_predictions_{suffix}.jsonl", results)
    write_json(report_dir / f"topic_summary_{suffix}.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

