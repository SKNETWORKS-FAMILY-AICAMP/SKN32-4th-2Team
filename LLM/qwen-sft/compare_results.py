"""기본 Qwen과 SFT 결과를 표와 블라인드 수동 검수지로 만든다."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from src.io_utils import read_jsonl
from src.settings import ROOT, SETTINGS


def main() -> int:
    report_dir = ROOT / "reports"
    base_summary = json.loads(
        (report_dir / "eval_summary_base.json").read_text(encoding="utf-8")
    )
    sft_summary = json.loads(
        (report_dir / "eval_summary_sft.json").read_text(encoding="utf-8")
    )
    for summary in (base_summary, sft_summary):
        if not (
            summary.get("canonical_run")
            and summary.get("questions") == 34
            and summary.get("repeats") == 3
            and summary.get("answers") == 102
        ):
            raise ValueError(
                "정식 비교는 각 variant의 34문항×3회(102답변) 결과만 허용합니다."
            )
    base_topic = json.loads(
        (report_dir / "topic_summary_base.json").read_text(encoding="utf-8")
    )
    sft_topic = json.loads(
        (report_dir / "topic_summary_sft.json").read_text(encoding="utf-8")
    )
    for summary in (base_topic, sft_topic):
        if not summary.get("canonical_run") or summary.get("questions") != 34:
            raise ValueError("정식 비교는 34문항 주제 분류 결과도 필요합니다.")
    base_rows = {
        (row["question_id"], row["repeat"]): row
        for row in read_jsonl(report_dir / "predictions_base.jsonl")
    }
    sft_rows = {
        (row["question_id"], row["repeat"]): row
        for row in read_jsonl(report_dir / "predictions_sft.jsonl")
    }
    if set(base_rows) != set(sft_rows):
        raise ValueError("base와 sft 평가 문항/반복 구성이 다릅니다.")

    randomizer = random.Random(SETTINGS.seed)
    review_path = report_dir / "manual_review.csv"
    mapping: dict[str, dict[str, str]] = {}
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = [
            "review_id",
            "question_id",
            "repeat",
            "question",
            "answer_a",
            "answer_b",
            "a_grounded_0_or_1",
            "b_grounded_0_or_1",
            "a_personal_number_safe_0_or_1",
            "b_personal_number_safe_0_or_1",
            "preferred_a_b_tie",
            "notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, key in enumerate(sorted(base_rows), start=1):
            base, sft = base_rows[key], sft_rows[key]
            if randomizer.random() < 0.5:
                answer_a, answer_b = base["answer"], sft["answer"]
                mapping[str(index)] = {"A": "base", "B": "sft"}
            else:
                answer_a, answer_b = sft["answer"], base["answer"]
                mapping[str(index)] = {"A": "sft", "B": "base"}
            writer.writerow(
                {
                    "review_id": index,
                    "question_id": key[0],
                    "repeat": key[1],
                    "question": base["question"],
                    "answer_a": answer_a,
                    "answer_b": answer_b,
                    "a_grounded_0_or_1": "",
                    "b_grounded_0_or_1": "",
                    "a_personal_number_safe_0_or_1": "",
                    "b_personal_number_safe_0_or_1": "",
                    "preferred_a_b_tie": "",
                    "notes": "",
                }
            )
    (report_dir / "manual_review_mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    def cell(summary: dict, key: str) -> object:
        return summary[key]

    markdown = f"""# Qwen 한국어 HR SFT 추가 실험 비교

| 지표 | Base Qwen2.5-7B | HR Korean SFT |
|---|---:|---:|
| 평가 답변 수 | {cell(base_summary, 'answers')} | {cell(sft_summary, 'answers')} |
| 언어 이탈 | {cell(base_summary, 'language_leaks')} | {cell(sft_summary, 'language_leaks')} |
| 오류 | {cell(base_summary, 'errors')} | {cell(sft_summary, 'errors')} |
| 문서 없음 안전 안내 실패 | {cell(base_summary, 'no_context_without_guard')} | {cell(sft_summary, 'no_context_without_guard')} |
| 주제 분류 정확도 | {base_topic['correct']}/34 | {sft_topic['correct']}/34 |
| RunPod 직접 추론 p50 | {base_summary['latency_ms']['p50']}ms | {sft_summary['latency_ms']['p50']}ms |
| RunPod 직접 추론 p95 | {base_summary['latency_ms']['p95']}ms | {sft_summary['latency_ms']['p95']}ms |

## 판정 전 남은 검수

- `manual_review.csv`의 34문항 × 반복 답변을 블라인드 검수합니다.
- SFT 주제 분류가 32/34 아래면 통합 후보에서 제외합니다.
- 문서 근거와 다른 숫자·조문·절차가 1건이라도 있으면 답변 모델 승격을 보류합니다.
- RunPod 지연시간은 로컬 Ollama 기준선과 비교하지 않습니다.
- 자동·수동 품질 통과 후에만 병합/GGUF/Ollama 변환과 동일 장비 최종 벤치를 진행합니다.
"""
    (report_dir / "comparison.md").write_text(markdown, encoding="utf-8")
    print(f"비교 보고서: {report_dir / 'comparison.md'}")
    print(f"블라인드 검수지: {review_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
