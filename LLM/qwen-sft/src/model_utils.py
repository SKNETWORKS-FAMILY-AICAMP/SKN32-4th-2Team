"""Qwen2.5 7B 4-bit 모델 로드와 생성 공통 코드."""

from __future__ import annotations

import torch
from peft import PeftModel, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from src.settings import SETTINGS


def compute_dtype() -> torch.dtype:
    if torch.cuda.is_available() and torch.cuda.is_bf16_supported():
        return torch.bfloat16
    return torch.float16


def quantization_config() -> BitsAndBytesConfig:
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype(),
    )


def load_tokenizer(path: str | None = None):
    tokenizer = AutoTokenizer.from_pretrained(
        path or SETTINGS.model_name,
        revision=None if path else SETTINGS.model_revision,
        token=SETTINGS.hf_token,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    return tokenizer


def load_base_model(*, for_training: bool):
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU를 찾지 못했습니다. RunPod GPU Pod에서 실행하세요.")
    model = AutoModelForCausalLM.from_pretrained(
        SETTINGS.model_name,
        revision=SETTINGS.model_revision,
        token=SETTINGS.hf_token,
        quantization_config=quantization_config(),
        device_map={"": 0},
        low_cpu_mem_usage=True,
    )
    model.config.pad_token_id = model.config.eos_token_id
    if for_training:
        model.config.use_cache = False
        model = prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=True
        )
        model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
    else:
        model.config.use_cache = True
        model.eval()
    return model


def load_inference_model(variant: str):
    if variant not in {"base", "sft"}:
        raise ValueError("variant는 base 또는 sft여야 합니다.")
    tokenizer_path = str(SETTINGS.adapter_dir) if variant == "sft" else None
    tokenizer = load_tokenizer(tokenizer_path)
    model = load_base_model(for_training=False)
    if variant == "sft":
        if not SETTINGS.adapter_dir.exists():
            raise FileNotFoundError(f"LoRA 어댑터가 없습니다: {SETTINGS.adapter_dir}")
        model = PeftModel.from_pretrained(model, str(SETTINGS.adapter_dir))
        model.eval()
    return model, tokenizer


def generate(
    model,
    tokenizer,
    messages: list[dict[str, str]],
    seed: int,
    *,
    max_new_tokens: int | None = None,
    do_sample: bool = True,
) -> str:
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    encoded = tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
    encoded = {key: value.to(model.device) for key, value in encoded.items()}
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    generation_kwargs = {
        "max_new_tokens": max_new_tokens or SETTINGS.max_new_tokens,
        "do_sample": do_sample,
        "repetition_penalty": 1.0,
        "pad_token_id": tokenizer.pad_token_id,
        "eos_token_id": tokenizer.eos_token_id,
    }
    if do_sample:
        generation_kwargs.update({"temperature": 0.2, "top_p": 0.9})
    with torch.inference_mode():
        generated = model.generate(**encoded, **generation_kwargs)
    answer_tokens = generated[:, encoded["input_ids"].shape[1] :]
    return tokenizer.batch_decode(answer_tokens, skip_special_tokens=True)[0].strip()
