"""분담 작성된 JSONL 초안을 하나의 candidates.jsonl로 합친다."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from src.io_utils import read_jsonl, write_jsonl

ROOT = Path(__file__).resolve().parent
DRAFT_DIR = ROOT / "data/drafts"
OUTPUT = ROOT / "data/candidates.jsonl"
EXPECTED_CATEGORIES = {
    "휴가/휴직": 14,
    "근태/근무형태": 14,
    "급여/보수": 12,
    "채용/임용": 12,
    "인사/승진": 12,
    "복리후생": 10,
    "복무/징계": 14,
    "기타": 12,
}
EXPECTED_CASE_TYPES = {
    "grounded": 78,
    "no_context": 10,
    "personal_data": 6,
    "conflicting_documents": 6,
}


def main() -> int:
    files = sorted(DRAFT_DIR.glob("*.jsonl"))
    if not files:
        raise FileNotFoundError(f"초안 파일이 없습니다: {DRAFT_DIR}")
    rows = [row for path in files for row in read_jsonl(path)]
    ids = [str(row.get("id") or "") for row in rows]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    categories = Counter(row.get("category") for row in rows)
    splits = Counter(row.get("split") for row in rows)
    case_types = Counter(row.get("case_type") for row in rows)
    errors = []
    if len(rows) != 100:
        errors.append(f"전체 {len(rows)}건 (기대 100건)")
    if duplicates:
        errors.append(f"중복 ID: {duplicates}")
    if dict(categories) != EXPECTED_CATEGORIES:
        errors.append(f"카테고리 집계 불일치: {dict(categories)}")
    if splits != Counter({"train": 80, "valid": 20}):
        errors.append(f"분할 집계 불일치: {dict(splits)}")
    if dict(case_types) != EXPECTED_CASE_TYPES:
        errors.append(f"case_type 집계 불일치: {dict(case_types)}")
    if any(row.get("approved") is not False for row in rows):
        errors.append("AI 초안은 모두 approved=false여야 합니다.")
    if errors:
        raise ValueError("초안 병합 실패:\n- " + "\n- ".join(errors))
    rows.sort(key=lambda row: (row["split"], row["category"], row["id"]))
    write_jsonl(OUTPUT, rows)
    print(
        json.dumps(
            {
                "files": [path.name for path in files],
                "rows": len(rows),
                "splits": dict(splits),
                "categories": dict(categories),
                "case_types": dict(case_types),
                "output": str(OUTPUT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
