"""학습 전 AI 초안의 Qwen 토큰 길이와 assistant-only 마스킹을 검사한다."""

from __future__ import annotations

import json
import math
from pathlib import Path

from prepare_dataset import context_from
from src.io_utils import read_jsonl, write_json
from src.model_utils import load_tokenizer
from src.settings import ROOT, SETTINGS
from train_qlora import tokenize_conversation


def percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def main() -> int:
    rows = read_jsonl(ROOT / "data/candidates.jsonl")
    system_prompt = (ROOT / "data/system_prompt.txt").read_text(encoding="utf-8").strip()
    tokenizer = load_tokenizer()
    lengths = []
    assistant_lengths = []
    details = []
    for row in rows:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"{context_from(row)}\n\n[질문]\n{row['question']}",
            },
            {"role": "assistant", "content": row["answer"]},
        ]
        tokenized = tokenize_conversation(
            {"id": row["id"], "messages": messages}, tokenizer, SETTINGS.max_length
        )
        total = len(tokenized["input_ids"])
        assistant = sum(label != -100 for label in tokenized["labels"])
        lengths.append(total)
        assistant_lengths.append(assistant)
        details.append(
            {"id": row["id"], "total_tokens": total, "assistant_tokens": assistant}
        )
    report = {
        "rows": len(rows),
        "max_length_setting": SETTINGS.max_length,
        "total_tokens": {
            "min": min(lengths),
            "p50": percentile(lengths, 0.50),
            "p95": percentile(lengths, 0.95),
            "max": max(lengths),
        },
        "assistant_tokens": {
            "min": min(assistant_lengths),
            "p50": percentile(assistant_lengths, 0.50),
            "p95": percentile(assistant_lengths, 0.95),
            "max": max(assistant_lengths),
        },
        "over_limit": [row for row in details if row["total_tokens"] > SETTINGS.max_length],
        "top_10_longest": sorted(
            details, key=lambda row: row["total_tokens"], reverse=True
        )[:10],
        "assistant_only_mask_verified": all(value > 0 for value in assistant_lengths),
    }
    write_json(ROOT / "reports/token_length_profile.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

