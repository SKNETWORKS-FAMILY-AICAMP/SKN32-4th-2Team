"""100개 AI 초안을 사람이 검수할 UTF-8 CSV로 내보낸다."""

from __future__ import annotations

import csv
from pathlib import Path

from src.io_utils import read_jsonl

ROOT = Path(__file__).resolve().parent


def main() -> int:
    candidates = read_jsonl(ROOT / "data/candidates.jsonl")
    output = ROOT / "reports/training_data_review.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "split",
        "category",
        "case_type",
        "intent_group",
        "question",
        "answer",
        "source_file_page",
        "evidence_text",
        "decision_yes_or_no",
        "reviewer",
        "review_note",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in candidates:
            evidence = row.get("evidence") or []
            writer.writerow(
                {
                    "id": row["id"],
                    "split": row["split"],
                    "category": row["category"],
                    "case_type": row["case_type"],
                    "intent_group": row["intent_group"],
                    "question": row["question"],
                    "answer": row["answer"],
                    "source_file_page": " | ".join(
                        f"{item['source_file']} p.{item['page']}" for item in evidence
                    ),
                    "evidence_text": " | ".join(item["text"] for item in evidence),
                    "decision_yes_or_no": "",
                    "reviewer": "",
                    "review_note": "",
                }
            )
    print(f"사람 검수 CSV: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

