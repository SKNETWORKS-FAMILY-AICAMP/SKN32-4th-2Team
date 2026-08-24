"""팀 저장소의 34문항과 이상적 RAG 문맥을 평가 전용 JSONL로 고정한다."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

import yaml

from src.io_utils import sha256_file, write_json, write_jsonl

ROOT = Path(__file__).resolve().parent
DEFAULT_TEAM_ROOT = Path(r"C:\Dev_Tools\other_team_project\SKN32-3rd-2Team")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--team-root", type=Path, default=DEFAULT_TEAM_ROOT)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    llm_dir = args.team_root / "LLM"
    questions_path = llm_dir / "bench/questions.yaml"
    prompts_path = llm_dir / "app/prompts.py"
    pdf_dir = args.team_root / "RAG/res/pdf"
    if not questions_path.exists() or not prompts_path.exists() or not pdf_dir.exists():
        raise FileNotFoundError(
            "팀 저장소에서 LLM/bench/questions.yaml, LLM/app/prompts.py, "
            "RAG/res/pdf를 찾지 못했습니다. --team-root를 확인하세요."
        )

    # corpus.py가 다른 기본 경로나 과거 캐시를 선택하지 못하도록 실제 팀 PDF를 고정한다.
    os.environ["BENCH_PDF_DIR"] = str(pdf_dir.resolve())
    sys.path.insert(0, str(llm_dir))
    sys.path.insert(0, str(llm_dir / "bench"))
    corpus = importlib.import_module("corpus")
    prompts = importlib.import_module("app.prompts")
    corpus.CACHE_PATH = ROOT / "data/corpus_cache.json"

    raw = yaml.safe_load(questions_path.read_text(encoding="utf-8"))
    questions = raw["questions"]
    # 28개/380쪽 규모라 매번 원문에서 다시 읽어도 짧다. stale cache보다 재현성이 중요하다.
    loaded = corpus.load_corpus(refresh=True)
    rows: list[dict] = []
    for question in questions:
        chunks = corpus.search(
            question["question"],
            question.get("sources") or [],
            top_k=args.top_k,
            corpus=loaded,
        )
        context = prompts.build_answer_context(chunks)
        rows.append(
            {
                "id": question["id"],
                "group": question.get("group"),
                "question": question["question"],
                "expected_topic": question["category"],
                "expected_sources": question.get("sources") or [],
                "out_of_scope": bool(question.get("out_of_scope")),
                "note": question.get("note"),
                "retrieved_sources": [
                    {
                        "file": chunk.original_file_name,
                        "page": chunk.page,
                        "score": chunk.score,
                    }
                    for chunk in chunks
                ],
                "messages": [
                    {"role": "system", "content": prompts.ANSWER_SYSTEM},
                    {
                        "role": "user",
                        "content": f"{context}\n\n[질문]\n{question['question']}",
                    },
                ],
                "topic_messages": [
                    {"role": "system", "content": prompts.TOPIC_SYSTEM},
                    {
                        "role": "user",
                        "content": prompts.build_topic_input(
                            question["question"], question.get("sources") or []
                        ),
                    },
                ],
            }
        )

    output = ROOT / "data/holdout.jsonl"
    prompt_output = ROOT / "data/system_prompt.txt"
    topic_prompt_output = ROOT / "data/topic_system_prompt.txt"
    write_jsonl(output, rows)
    prompt_output.write_text(prompts.ANSWER_SYSTEM.strip() + "\n", encoding="utf-8")
    topic_prompt_output.write_text(prompts.TOPIC_SYSTEM.strip() + "\n", encoding="utf-8")
    manifest = {
        "purpose": "evaluation_only_do_not_train",
        "question_count": len(rows),
        "top_k": args.top_k,
        "questions_source": str(questions_path.resolve()),
        "pdf_source": str(pdf_dir.resolve()),
        "questions_sha256": sha256_file(questions_path),
        "prompts_py_sha256": sha256_file(prompts_path),
        "holdout_sha256": sha256_file(output),
        "system_prompt_sha256": sha256_file(prompt_output),
        "topic_system_prompt_sha256": sha256_file(topic_prompt_output),
    }
    write_json(ROOT / "data/holdout_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
