"""환경설정. 값은 전부 .env 에서만 온다 (키 하드코딩 금지)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LLM_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=LLM_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 서비스 ---
    llm_service_port: int = 8002
    default_provider: Literal["openai", "gemini"] = "openai"
    llm_timeout_sec: float = 15.0

    # 답변 길이 안전 상한. 실제 길이는 질문 복잡도에 맞춰 프롬프트가 조절하므로
    # 모델이 안 지킬 수 있다 — Qwen2.5:7b 는 벤치에서 2415자를 57초에 걸쳐
    # 뱉었다. 지시를 안 지키는 모델 때문에 사용자가 기다리는 일이 없도록
    # 디코더 단에서 막는다. 정상 답변은 중앙값 226자(≈200토큰)라 여유가 있다.
    answer_max_tokens: int = 500

    # 답변에 조문 번호를 인용할 것인가.
    #
    # **현재 RAG 구성에서는 끈다.** 청크가 조문 중간부터 시작해 정작 내용의 주인인
    # 조문 머리가 컨텍스트에 없는 일이 잦다. 그러면 모델이 청크 뒤쪽에 보이는
    # **다른 조문**을 인용한다. 실측 예:
    #
    #   휴일근로 수당(제56조) 내용을 설명하며 "(근로기준법 제57조)" 라고 답함
    #   — 제57조는 보상 휴가제라 무관하다. 그런데 그 청크에 제57조 머리가
    #     글자로 들어 있어 "근거에 있는 조문인가" 검사로는 걸러낼 수 없다.
    #
    # 형식이 멀쩡한 오인용은 없는 것만 못하다. 직원이 그대로 믿고 엉뚱한 조문을
    # 찾아간다. 그래서 규정 이름까지만("근로기준법에 따르면") 남긴다.
    #
    # RAG 가 청크에 조문 머리를 붙여 주면(docs/RAG_FEEDBACK.md 4-1, 패치 첨부)
    # 이 값을 true 로 바꾸면 된다. 그 구성에서 실측한 결과는 인용 11건 / 오류 0건이었다.
    answer_cite_articles: bool = False
    # 고위험 급여·휴직·징계 답변은 근거 ID/숫자 검사에 더해 의미적 누락·범위
    # 축약을 enum 제약 판정으로 한 번 확인한다. all은 모든 ANSWER/NOT_FOUND,
    # off는 로컬 성능 비교용이다.
    answer_verify_mode: Literal["off", "risky", "all"] = "risky"

    # live = 실제 API 호출 / mock = 고정 응답.
    # API 키 없이도 팀원이 UI를 붙여볼 수 있게 하는 용도. 공개 API 계약은 동일하다.
    llm_mode: Literal["live", "mock"] = "live"

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # --- Gemini ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"

    # --- Qwen (로컬 오픈소스, Ollama 경유) ---
    # 상용 API 와의 비교용. 키가 필요 없는 대신 로컬에 Ollama 가 떠 있어야 한다.
    qwen_base_url: str = "http://localhost:11434"
    qwen_model: str = "qwen2.5:7b"
    # Ollama 는 기본 5분 미사용 시 모델을 메모리에서 내린다. 그러면 다음 호출이
    # 모델 로딩(실측 4초)을 다시 문다. 시연 중 잠깐 쉬면 그대로 드러나므로
    # 넉넉히 잡아 상주시킨다. VRAM 4.75GB 를 계속 점유한다(8GB 중).
    qwen_keep_alive: str = "30m"

    # --- 주제 분류 방법 ---
    # llm   : 현행. 프로바이더에 enum 제약 호출을 한 번 더 보낸다
    # embed : 질문 임베딩과 카테고리 임베딩의 유사도로 분류. API 호출 없음
    topic_method: Literal["llm", "embed"] = "llm"
    topic_embed_model: str = "jhgan/ko-sroberta-multitask"

    # --- RAG ---
    rag_mode: Literal["live", "mock"] = "mock"
    rag_base_url: str = "http://localhost:8001"
    rag_timeout_sec: float = 45.0
    rag_top_k: int = 5

    # 관련도가 이 값 미만인 검색 결과는 버린다.
    #
    # RAG 는 관련 문서가 없어도 top_k 를 무관한 청크로 채워서 돌려준다. 그러면
    # 모델이 "근거가 있다" 고 착각하고, 문서에 없는 수치를 지어낸다. 실제로
    # "연차 며칠까지 쓸 수 있나요?" 에 복무규정이 검색되지 않았는데도 15일·25일
    # 같은 숫자를 단언했다. 규정 안내 서비스에서 가장 위험한 실패다.
    #
    # 34문항 실측 리랭커 점수 분포:
    #   검색 성공 27건   최저 0.0672  중앙 0.8296
    #   검색 놓침  4건   0.0059 ~ 0.2002
    #   범위 밖    3건   0.0001 ~ 0.0021
    # 성공 최저(0.067)와 범위 밖 최고(0.002) 사이가 30배 넘게 비어 있다.
    # 0.01 은 양쪽에서 5배 이상 떨어져 있어 안전하다.
    #
    # 걸러낸 결과 문서가 하나도 안 남으면 근거 없이 답하는 대신 "찾을 수 없습니다"
    # 로 안내한다. 검색 자체는 성공했으므로 rag_degraded 는 False 다.
    # 0 으로 두면 이 기능이 꺼진다.
    rag_min_score: float = 0.01

    # --- 계측 ---
    metrics_path: str = "logs/metrics.jsonl"
    metrics_enabled: bool = True

    def is_configured(self, provider: str) -> bool:
        if self.llm_mode == "mock":
            return True
        # 로컬 프로바이더는 API 키가 없다. 키 유무로 판단하면 항상 미설정이 된다.
        from app.providers.registry import KEYLESS

        if provider in KEYLESS:
            return True
        return bool(getattr(self, f"{provider}_api_key", ""))

    @property
    def metrics_file(self) -> Path:
        p = Path(self.metrics_path)
        return p if p.is_absolute() else LLM_DIR / p


@lru_cache
def get_settings() -> Settings:
    return Settings()
