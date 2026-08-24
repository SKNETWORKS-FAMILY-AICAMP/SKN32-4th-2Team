"""환경변수 기반 실험 설정."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else ROOT / value


@dataclass(frozen=True)
class Settings:
    model_name: str = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct")
    model_revision: str = os.getenv(
        "MODEL_REVISION", "a09a35458c702b33eeacc393d103063234e8bc28"
    )
    hf_token: str | None = os.getenv("HF_TOKEN") or None
    adapter_dir: Path = _path(
        "ADAPTER_DIR", "outputs/qwen2.5-7b-hr-korean-lora"
    )
    train_file: Path = _path("TRAIN_FILE", "data/train.jsonl")
    valid_file: Path = _path("VALID_FILE", "data/valid.jsonl")
    holdout_file: Path = _path("HOLDOUT_FILE", "data/holdout.jsonl")
    seed: int = int(os.getenv("SEED", "42"))
    max_length: int = int(os.getenv("MAX_LENGTH", "1024"))
    max_new_tokens: int = int(os.getenv("MAX_NEW_TOKENS", "500"))
    train_batch_size: int = int(os.getenv("TRAIN_BATCH_SIZE", "1"))
    eval_batch_size: int = int(os.getenv("EVAL_BATCH_SIZE", "1"))
    gradient_accumulation_steps: int = int(
        os.getenv("GRADIENT_ACCUMULATION_STEPS", "8")
    )
    num_train_epochs: float = float(os.getenv("NUM_TRAIN_EPOCHS", "3"))
    learning_rate: float = float(os.getenv("LEARNING_RATE", "0.0001"))
    lora_r: int = int(os.getenv("LORA_R", "16"))
    lora_alpha: int = int(os.getenv("LORA_ALPHA", "32"))
    lora_dropout: float = float(os.getenv("LORA_DROPOUT", "0.05"))
    latency_gate_ms: int = int(os.getenv("LATENCY_GATE_MS", "5000"))
    eval_repeats: int = int(os.getenv("EVAL_REPEATS", "3"))

    def public_dict(self) -> dict[str, object]:
        """토큰을 제외한 재현성 기록용 설정을 반환한다."""
        values = asdict(self)
        values.pop("hf_token", None)
        return {key: str(value) if isinstance(value, Path) else value for key, value in values.items()}


SETTINGS = Settings()
