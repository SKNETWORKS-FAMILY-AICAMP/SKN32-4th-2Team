"""AI 작성 초안의 구조·누수·PII·PDF 근거 일치를 검증한다."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pypdf

from prepare_dataset import validate_and_convert
from src.io_utils import read_jsonl, write_json

ROOT = Path(__file__).resolve().parent
DEFAULT_PDF_DIR = Path(
    r"C:\Dev_Tools\other_team_project\SKN32-3rd-2Team\RAG\res\pdf"
)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def sentence_count(answer: str) -> int:
    return len([part for part in re.split(r"(?<=[.!?])\s+", answer.strip()) if part])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=ROOT / "data/candidates.jsonl")
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    args = parser.parse_args()

    rows = read_jsonl(args.candidates)
    holdout = read_jsonl(ROOT / "data/holdout.jsonl")
    system_prompt = (ROOT / "data/system_prompt.txt").read_text(encoding="utf-8").strip()
    structural_rows = [
        {**row, "approved": True, "reviewer": "AI structural validator"}
        for row in rows
    ]
    # 기존 prepare_dataset과 같은 누수·PII·split 검사를 초안에도 강제한다.
    validate_and_convert(structural_rows, holdout, system_prompt)

    page_cache: dict[tuple[str, int], str] = {}
    evidence_errors: list[str] = []
    sentence_errors: list[str] = []
    for row in rows:
        count = sentence_count(str(row.get("answer") or ""))
        if not 3 <= count <= 6:
            sentence_errors.append(f"{row['id']}: {count}문장")
        for item in row.get("evidence") or []:
            source = args.pdf_dir / item["source_file"]
            page_no = int(item["page"])
            if not source.exists():
                evidence_errors.append(f"{row['id']}: PDF 없음 {source.name}")
                continue
            key = (source.name, page_no)
            if key not in page_cache:
                reader = pypdf.PdfReader(str(source))
                if page_no < 1 or page_no > len(reader.pages):
                    evidence_errors.append(
                        f"{row['id']}: 페이지 범위 오류 {source.name} p.{page_no}"
                    )
                    continue
                page_cache[key] = compact(reader.pages[page_no - 1].extract_text() or "")
            excerpt = compact(str(item.get("text") or ""))
            if excerpt not in page_cache.get(key, ""):
                evidence_errors.append(
                    f"{row['id']}: 원문 불일치 {source.name} p.{page_no}"
                )
    if sentence_errors or evidence_errors:
        parts = []
        if sentence_errors:
            parts.append("문장 수 오류:\n- " + "\n- ".join(sentence_errors))
        if evidence_errors:
            parts.append("PDF 근거 오류:\n- " + "\n- ".join(evidence_errors))
        raise ValueError("\n".join(parts))

    report = {
        "status": "structural_and_evidence_checks_passed_ai_drafts_not_human_approved",
        "rows": len(rows),
        "splits": dict(Counter(row["split"] for row in rows)),
        "categories": dict(Counter(row["category"] for row in rows)),
        "case_types": dict(Counter(row["case_type"] for row in rows)),
        "intent_groups": len({row["intent_group"] for row in rows}),
        "verified_pdf_pages": len(page_cache),
        "human_approval_required": True,
    }
    write_json(ROOT / "reports/draft_validation.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
