"""검수 승인된 HR 후보를 학습/검증 JSONL로 변환한다."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from src.io_utils import read_jsonl, sha256_file, write_json, write_jsonl

ROOT = Path(__file__).resolve().parent
CATEGORIES = {
    "휴가/휴직",
    "근태/근무형태",
    "급여/보수",
    "채용/임용",
    "인사/승진",
    "복리후생",
    "복무/징계",
    "기타",
}
CASE_TYPES = {"grounded", "no_context", "personal_data", "conflicting_documents"}
PII_PATTERNS = {
    "주민등록번호": re.compile(r"\b\d{6}\s*[- ]\s*[1-4]\d{6}\b"),
    "이메일": re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    "전화번호": re.compile(r"\b01[016789][ -]?\d{3,4}[ -]?\d{4}\b"),
    "사번": re.compile(r"(?:사번|직원번호)\s*[:：]?\s*[A-Za-z0-9-]{4,}"),
}


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^0-9a-z가-힣]", "", normalized)


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()


def context_from(row: dict) -> str:
    evidence = row.get("evidence") or []
    if not evidence:
        return (
            "[참고 문서]\n"
            "(검색된 문서가 없습니다. 일반적인 안내만 제공하고, 정확한 내용은 "
            "인사팀 확인이 필요하다고 안내하세요.)"
        )
    blocks = []
    for index, item in enumerate(evidence, start=1):
        page = f" p.{item['page']}" if item.get("page") else ""
        blocks.append(
            f"[문서 {index}] {item['source_file']}{page}\n{item['text'].strip()}"
        )
    return "[참고 문서]\n" + "\n\n".join(blocks)


def find_pii(text: str) -> list[str]:
    return [name for name, pattern in PII_PATTERNS.items() if pattern.search(text)]


def validate_and_convert(
    candidates: list[dict], holdout: list[dict], system_prompt: str
) -> tuple[list[dict], list[dict], dict]:
    approved = [row for row in candidates if row.get("approved") is True]
    errors: list[str] = []
    seen_ids: set[str] = set()
    split_groups: dict[str, set[str]] = {"train": set(), "valid": set()}
    holdout_questions = [(row["id"], row["question"]) for row in holdout]
    holdout_groups = {row.get("group") for row in holdout if row.get("group")}
    converted: dict[str, list[dict]] = {"train": [], "valid": []}

    for row in approved:
        row_id = str(row.get("id") or "<id 없음>")
        if row_id in seen_ids:
            errors.append(f"{row_id}: 중복 ID")
        seen_ids.add(row_id)

        split = row.get("split")
        group = str(row.get("intent_group") or "").strip()
        category = row.get("category")
        case_type = row.get("case_type")
        question = str(row.get("question") or "").strip()
        answer = str(row.get("answer") or "").strip()
        reviewer = str(row.get("reviewer") or "").strip()
        evidence = row.get("evidence") or []

        if split not in converted:
            errors.append(f"{row_id}: split은 train 또는 valid여야 함")
            continue
        if not group:
            errors.append(f"{row_id}: intent_group 없음")
        elif group in holdout_groups:
            errors.append(f"{row_id}: 홀드아웃 intent_group과 충돌({group})")
        else:
            split_groups[split].add(group)
        if category not in CATEGORIES:
            errors.append(f"{row_id}: 허용되지 않은 category({category})")
        if case_type not in CASE_TYPES:
            errors.append(f"{row_id}: 허용되지 않은 case_type({case_type})")
        if not question or not answer:
            errors.append(f"{row_id}: question 또는 answer가 비어 있음")
        if not reviewer:
            errors.append(f"{row_id}: 승인 샘플에 reviewer가 없음")
        if case_type in {"grounded", "conflicting_documents"} and not evidence:
            errors.append(f"{row_id}: 근거가 필요한 case_type인데 evidence가 없음")
        if case_type == "conflicting_documents" and len(evidence) < 2:
            errors.append(f"{row_id}: conflicting_documents는 evidence가 2개 이상이어야 함")

        valid_evidence = []
        for item in evidence:
            if not isinstance(item, dict):
                errors.append(f"{row_id}: evidence 항목은 객체여야 함")
                continue
            if not item.get("source_file") or not item.get("page") or not str(item.get("text") or "").strip():
                errors.append(f"{row_id}: evidence의 파일명·페이지·본문이 불완전함")
                continue
            valid_evidence.append(item)

        pii = find_pii("\n".join([question, answer] + [str(e.get("text") or "") for e in evidence]))
        if pii:
            errors.append(f"{row_id}: 개인정보 패턴 발견({', '.join(pii)})")

        for holdout_id, holdout_question in holdout_questions:
            score = similarity(question, holdout_question)
            if score >= 0.85:
                errors.append(
                    f"{row_id}: 홀드아웃 {holdout_id}와 질문 유사도 {score:.2f}"
                )
            elif score >= 0.60 and not (
                str(row.get("holdout_overlap_reviewed_by") or "").strip()
                and str(row.get("holdout_overlap_note") or "").strip()
            ):
                errors.append(
                    f"{row_id}: 홀드아웃 {holdout_id}와 중간 유사도 {score:.2f}; "
                    "의미 중복 수동 검토 후 holdout_overlap_reviewed_by/note 기록 필요"
                )

        context = context_from({**row, "evidence": valid_evidence})
        converted[split].append(
            {
                "id": row_id,
                "intent_group": group,
                "category": category,
                "case_type": case_type,
                "sources": [
                    {"file": e.get("source_file"), "page": e.get("page")}
                    for e in valid_evidence
                ],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"{context}\n\n[질문]\n{question}",
                    },
                    {"role": "assistant", "content": answer},
                ],
            }
        )

    overlap = split_groups["train"] & split_groups["valid"]
    if overlap:
        errors.append(f"train/valid intent_group 중복: {sorted(overlap)}")
    if errors:
        raise ValueError("데이터 검증 실패:\n- " + "\n- ".join(errors))

    report = {
        "approved_candidates": len(approved),
        "train_count": len(converted["train"]),
        "valid_count": len(converted["valid"]),
        "category_counts": dict(Counter(row["category"] for row in approved)),
        "case_type_counts": dict(Counter(row["case_type"] for row in approved)),
        "train_intent_groups": len(split_groups["train"]),
        "valid_intent_groups": len(split_groups["valid"]),
        "pii_findings": 0,
        "holdout_similarity_threshold": 0.85,
    }
    return converted["train"], converted["valid"], report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=ROOT / "data/candidates.jsonl")
    parser.add_argument("--holdout", type=Path, default=ROOT / "data/holdout.jsonl")
    parser.add_argument("--system-prompt", type=Path, default=ROOT / "data/system_prompt.txt")
    parser.add_argument("--allow-small", action="store_true")
    args = parser.parse_args()

    for path in (args.candidates, args.holdout, args.system_prompt):
        if not path.exists():
            raise FileNotFoundError(f"필수 파일이 없습니다: {path}")

    train, valid, report = validate_and_convert(
        read_jsonl(args.candidates),
        read_jsonl(args.holdout),
        args.system_prompt.read_text(encoding="utf-8").strip(),
    )
    min_train = 1 if args.allow_small else int(__import__("os").getenv("MIN_TRAIN_SAMPLES", "80"))
    min_valid = 1 if args.allow_small else int(__import__("os").getenv("MIN_VALID_SAMPLES", "20"))
    if len(train) < min_train or len(valid) < min_valid:
        raise ValueError(
            f"승인 데이터 부족: train={len(train)}/{min_train}, valid={len(valid)}/{min_valid}"
        )

    train_path = ROOT / "data/train.jsonl"
    valid_path = ROOT / "data/valid.jsonl"
    write_jsonl(train_path, train)
    write_jsonl(valid_path, valid)
    report.update(
        {
            "candidate_sha256": sha256_file(args.candidates),
            "holdout_sha256": sha256_file(args.holdout),
            "system_prompt_sha256": sha256_file(args.system_prompt),
            "train_sha256": sha256_file(train_path),
            "valid_sha256": sha256_file(valid_path),
        }
    )
    write_json(ROOT / "reports/dataset_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
