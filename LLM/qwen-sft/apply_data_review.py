"""사람이 채운 검수 CSV의 결정을 candidates.jsonl에 반영한다."""

from __future__ import annotations

import csv
from pathlib import Path

from src.io_utils import read_jsonl, write_jsonl

ROOT = Path(__file__).resolve().parent


def main() -> int:
    candidates_path = ROOT / "data/candidates.jsonl"
    review_path = ROOT / "reports/training_data_review.csv"
    candidates = read_jsonl(candidates_path)
    with review_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reviews = {row["id"]: row for row in csv.DictReader(handle)}
    candidate_ids = {row["id"] for row in candidates}
    if set(reviews) != candidate_ids:
        raise ValueError("검수 CSV와 candidates.jsonl의 ID 구성이 다릅니다.")

    errors = []
    approved = 0
    for row in candidates:
        review = reviews[row["id"]]
        decision = review["decision_yes_or_no"].strip().lower()
        reviewer = review["reviewer"].strip()
        if decision not in {"yes", "no"}:
            errors.append(f"{row['id']}: decision은 yes 또는 no여야 함")
            continue
        if not reviewer:
            errors.append(f"{row['id']}: reviewer가 비어 있음")
            continue
        row["approved"] = decision == "yes"
        row["reviewer"] = reviewer
        row["notes"] = review["review_note"].strip() or row.get("notes", "")
        approved += int(row["approved"])
    if errors:
        raise ValueError("검수 반영 실패:\n- " + "\n- ".join(errors))
    write_jsonl(candidates_path, candidates)
    print(f"검수 반영 완료: approved={approved}, rejected={len(candidates) - approved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

