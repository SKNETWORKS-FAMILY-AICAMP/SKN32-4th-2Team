"""동일 GPU·동일 디코딩 설정으로 기본 Qwen과 SFT 어댑터를 평가한다."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path

# Hugging Face 캐시 위치는 transformers/peft가 간접 import되기 전에 적용한다.
from dotenv import load_dotenv

EARLY_ROOT = Path(__file__).resolve().parent
load_dotenv(EARLY_ROOT / ".env")

import torch

from src.io_utils import environment_manifest, read_jsonl, sha256_file, write_json, write_jsonl
from src.model_utils import generate, load_inference_model
from src.settings import ROOT, SETTINGS

_HAN = re.compile(r"[一-鿿]")
_HANGUL = re.compile(r"[가-힣]")
_JAPANESE = re.compile(r"[ぁ-ゖァ-ヺ]")
_ENGLISH_SENTENCE = re.compile(r"(?:\b[A-Za-z]{2,}\b[\s,.;:!?-]*){4,}")
_REFUSAL_HINTS = ("찾을 수 없습니다", "확인이 필요", "인사팀", "담당 부서", "답변하기 어렵")


def language_flags(answer: str) -> list[str]:
    flags: list[str] = []
    han = len(_HAN.findall(answer))
    hangul = len(_HANGUL.findall(answer))
    if han and han > hangul * 0.1:
        flags.append("han_ratio_over_10pct")
    if _JAPANESE.search(answer):
        flags.append("japanese_script")
    if _ENGLISH_SENTENCE.search(answer):
        flags.append("english_sentence")
    return flags


def percentile(values: list[int], percent: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percent) - 1)
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", required=True, choices=["base", "sft"])
    parser.add_argument("--repeats", type=int, default=SETTINGS.eval_repeats)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    rows = read_jsonl(SETTINGS.holdout_file)
    if args.limit:
        rows = rows[: args.limit]
    model, tokenizer = load_inference_model(args.variant)

    # 모델 로딩 및 첫 CUDA 커널 컴파일 시간을 문항 지연시간에서 제외한다.
    _ = generate(model, tokenizer, rows[0]["messages"], SETTINGS.seed)
    torch.cuda.synchronize()

    results: list[dict] = []
    for repeat in range(args.repeats):
        for index, row in enumerate(rows):
            seed = SETTINGS.seed + repeat * 10_000 + index
            torch.cuda.synchronize()
            started = time.perf_counter()
            error = None
            answer = ""
            try:
                answer = generate(model, tokenizer, row["messages"], seed)
            except Exception as exc:  # 평가 전체를 보존하기 위해 행 단위로 기록한다.
                error = f"{type(exc).__name__}: {exc}"
            torch.cuda.synchronize()
            latency_ms = int((time.perf_counter() - started) * 1000)
            flags = language_flags(answer)
            no_context_without_guard = bool(
                row.get("out_of_scope")
                and not any(hint in answer for hint in _REFUSAL_HINTS)
            )
            result = {
                "variant": args.variant,
                "repeat": repeat + 1,
                "question_id": row["id"],
                "question": row["question"],
                "out_of_scope": row.get("out_of_scope", False),
                "expected_sources": row.get("expected_sources") or [],
                "answer": answer,
                "answer_chars": len(answer),
                "latency_ms": latency_ms,
                "language_flags": flags,
                "no_context_without_guard": no_context_without_guard,
                "manual_grounding_review_required": True,
                "error": error,
            }
            results.append(result)
            status = "ERROR" if error else ("LANG" if flags else "OK")
            print(
                f"[{len(results):03d}/{len(rows) * args.repeats}] "
                f"{row['id']} {latency_ms}ms {status}"
            )

    latencies = [row["latency_ms"] for row in results if not row["error"]]
    summary = {
        "variant": args.variant,
        "model": SETTINGS.model_name,
        "adapter": str(SETTINGS.adapter_dir) if args.variant == "sft" else None,
        "questions": len(rows),
        "repeats": args.repeats,
        "canonical_run": bool(not args.limit and len(rows) == 34 and args.repeats == 3),
        "answers": len(results),
        "errors": sum(bool(row["error"]) for row in results),
        "language_leaks": sum(bool(row["language_flags"]) for row in results),
        "han_ratio_leaks": sum(
            "han_ratio_over_10pct" in row["language_flags"] for row in results
        ),
        "japanese_leaks": sum(
            "japanese_script" in row["language_flags"] for row in results
        ),
        "english_sentence_leaks": sum(
            "english_sentence" in row["language_flags"] for row in results
        ),
        "no_context_without_guard": sum(
            row["no_context_without_guard"] for row in results
        ),
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": max(latencies, default=0),
        },
        "automatic_gates": {
            "language_zero": not any(row["language_flags"] for row in results),
            "error_zero": not any(row["error"] for row in results),
            "no_context_guard_zero": not any(
                row["no_context_without_guard"] for row in results
            ),
            "runpod_direct_p95_under_gate": percentile(latencies, 0.95)
            <= SETTINGS.latency_gate_ms,
        },
        "notes": [
            "사실 정확도와 개인 수치 생성 여부는 34문항 전체를 수동 검수해야 합니다.",
            "RunPod Transformers 지연시간은 로컬 Ollama 지연시간과 직접 비교하지 않습니다.",
            "최종 채택 전 같은 로컬 장비와 같은 Ollama 양자화 조건으로 다시 측정합니다.",
        ],
        "holdout_sha256": sha256_file(SETTINGS.holdout_file),
        "environment": environment_manifest(),
    }
    output_dir = ROOT / "reports"
    suffix = (
        args.variant
        if summary["canonical_run"]
        else f"{args.variant}_smoke_{len(rows)}q_{args.repeats}r"
    )
    write_jsonl(output_dir / f"predictions_{suffix}.jsonl", results)
    write_json(output_dir / f"eval_summary_{suffix}.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
