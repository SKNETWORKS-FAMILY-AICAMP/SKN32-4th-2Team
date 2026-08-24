"""Qwen2.5-7B-Instruct에 assistant-only 4-bit QLoRA SFT를 수행한다."""

from __future__ import annotations

import inspect
import json
import random
from dataclasses import dataclass
from pathlib import Path

# Hugging Face 캐시 위치는 transformers import 전에 적용되어야 한다.
from dotenv import load_dotenv

EARLY_ROOT = Path(__file__).resolve().parent
load_dotenv(EARLY_ROOT / ".env")

import numpy as np
import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import AutoTokenizer, Trainer, TrainingArguments

from src.io_utils import environment_manifest, read_jsonl, sha256_file, write_json
from src.model_utils import compute_dtype, load_base_model, load_tokenizer
from src.settings import ROOT, SETTINGS


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def tokenize_conversation(row: dict, tokenizer, max_length: int) -> dict:
    messages = row.get("messages") or []
    if [message.get("role") for message in messages] != ["system", "user", "assistant"]:
        raise ValueError(f"{row.get('id')}: messages 역할은 system/user/assistant여야 합니다.")

    prompt_text = tokenizer.apply_chat_template(
        messages[:-1], tokenize=False, add_generation_prompt=True
    )
    full_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False
    )
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(full_text, add_special_tokens=False)["input_ids"]
    if full_ids[: len(prompt_ids)] != prompt_ids:
        raise ValueError(f"{row.get('id')}: 채팅 템플릿의 prompt prefix가 일치하지 않습니다.")
    if len(full_ids) > max_length:
        raise ValueError(
            f"{row.get('id')}: {len(full_ids)} tokens로 MAX_LENGTH={max_length}를 초과합니다. "
            "근거 문장을 줄이거나 MAX_LENGTH를 검토하세요."
        )
    labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids) :]
    if not any(label != -100 for label in labels):
        raise ValueError(f"{row.get('id')}: 학습할 assistant 토큰이 없습니다.")
    return {
        "input_ids": full_ids,
        "attention_mask": [1] * len(full_ids),
        "labels": labels,
    }


@dataclass
class AssistantOnlyCollator:
    tokenizer: AutoTokenizer
    pad_to_multiple_of: int = 8

    def __call__(self, features: list[dict]) -> dict[str, torch.Tensor]:
        max_len = max(len(feature["input_ids"]) for feature in features)
        if self.pad_to_multiple_of:
            multiple = self.pad_to_multiple_of
            max_len = ((max_len + multiple - 1) // multiple) * multiple
        input_ids, attention_masks, labels = [], [], []
        for feature in features:
            padding = max_len - len(feature["input_ids"])
            input_ids.append(feature["input_ids"] + [self.tokenizer.pad_token_id] * padding)
            attention_masks.append(feature["attention_mask"] + [0] * padding)
            labels.append(feature["labels"] + [-100] * padding)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_masks, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }


def training_arguments() -> TrainingArguments:
    checkpoint_dir = SETTINGS.adapter_dir.parent / "checkpoints"
    kwargs: dict[str, object] = {
        "output_dir": str(checkpoint_dir),
        "num_train_epochs": SETTINGS.num_train_epochs,
        "per_device_train_batch_size": SETTINGS.train_batch_size,
        "per_device_eval_batch_size": SETTINGS.eval_batch_size,
        "gradient_accumulation_steps": SETTINGS.gradient_accumulation_steps,
        "learning_rate": SETTINGS.learning_rate,
        "weight_decay": 0.01,
        "warmup_ratio": 0.05,
        "lr_scheduler_type": "cosine",
        "optim": "paged_adamw_8bit",
        "logging_steps": 1,
        "logging_first_step": True,
        "save_strategy": "epoch",
        "save_total_limit": 2,
        "load_best_model_at_end": True,
        "metric_for_best_model": "eval_loss",
        "greater_is_better": False,
        "bf16": compute_dtype() == torch.bfloat16,
        "fp16": compute_dtype() == torch.float16,
        "gradient_checkpointing": True,
        "gradient_checkpointing_kwargs": {"use_reentrant": False},
        "report_to": ["tensorboard"],
        "logging_dir": str(SETTINGS.adapter_dir.parent / "tensorboard"),
        "remove_unused_columns": False,
        "seed": SETTINGS.seed,
        "data_seed": SETTINGS.seed,
    }
    parameters = inspect.signature(TrainingArguments.__init__).parameters
    kwargs["eval_strategy" if "eval_strategy" in parameters else "evaluation_strategy"] = "epoch"
    return TrainingArguments(**kwargs)


def main() -> int:
    seed_everything(SETTINGS.seed)
    for path in (SETTINGS.train_file, SETTINGS.valid_file, SETTINGS.holdout_file):
        if not path.exists():
            raise FileNotFoundError(f"필수 데이터 파일이 없습니다: {path}")

    train_rows = read_jsonl(SETTINGS.train_file)
    valid_rows = read_jsonl(SETTINGS.valid_file)
    holdout_ids = {row["id"] for row in read_jsonl(SETTINGS.holdout_file)}
    leaked_ids = holdout_ids & {row["id"] for row in train_rows + valid_rows}
    if leaked_ids:
        raise ValueError(f"홀드아웃 ID가 학습 데이터에 포함됨: {sorted(leaked_ids)}")

    tokenizer = load_tokenizer()
    train_dataset = Dataset.from_list(train_rows).map(
        lambda row: tokenize_conversation(row, tokenizer, SETTINGS.max_length),
        remove_columns=list(train_rows[0]),
        desc="train 토큰화 및 assistant-only 마스킹",
    )
    valid_dataset = Dataset.from_list(valid_rows).map(
        lambda row: tokenize_conversation(row, tokenizer, SETTINGS.max_length),
        remove_columns=list(valid_rows[0]),
        desc="valid 토큰화 및 assistant-only 마스킹",
    )

    model = load_base_model(for_training=True)
    lora = LoraConfig(
        r=SETTINGS.lora_r,
        lora_alpha=SETTINGS.lora_alpha,
        lora_dropout=SETTINGS.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    trainer = Trainer(
        model=model,
        args=training_arguments(),
        train_dataset=train_dataset,
        eval_dataset=valid_dataset,
        data_collator=AssistantOnlyCollator(tokenizer),
    )
    train_result = trainer.train()
    eval_metrics = trainer.evaluate()
    SETTINGS.adapter_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(SETTINGS.adapter_dir))
    tokenizer.save_pretrained(str(SETTINGS.adapter_dir))

    prompt_path = ROOT / "data/system_prompt.txt"
    manifest = {
        "settings": SETTINGS.public_dict(),
        "resolved_model_commit": getattr(model.config, "_commit_hash", None),
        "data": {
            "train_count": len(train_rows),
            "valid_count": len(valid_rows),
            "train_sha256": sha256_file(SETTINGS.train_file),
            "valid_sha256": sha256_file(SETTINGS.valid_file),
            "holdout_sha256": sha256_file(SETTINGS.holdout_file),
            "system_prompt_sha256": sha256_file(prompt_path) if prompt_path.exists() else None,
        },
        "assistant_only_loss": True,
        "train_metrics": train_result.metrics,
        "eval_metrics": eval_metrics,
        "environment": environment_manifest(),
    }
    write_json(SETTINGS.adapter_dir / "run_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
