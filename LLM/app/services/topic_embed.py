"""Zero-shot 임베딩 유사도 기반 주제 분류.

평가 질문이나 정답 라벨을 읽지 않는다. 카테고리 이름과 일반적인 설명 문장만
임베딩하므로, ``bench/questions.yaml``의 34문항은 순수하게 평가에만 남는다.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from app.config import get_settings
from app.domain import FALLBACK_TOPIC, TOPIC_CATEGORIES
from app.errors import ProviderUnavailable

# TOPIC_CATEGORIES 순서와 1:1로 대응하는 일반 설명이다. 카테고리 이름은 별도로
# 하드코딩하지 않고, 아래 설명과 TOPIC_CATEGORIES를 zip해 모델 입력을 만든다.
_DESCRIPTION_TEMPLATES: tuple[str, ...] = (
    "연차, 휴가, 병가, 출산휴가, 육아휴직, 가족돌봄휴직과 신청·사용 기준 문의",
    "출퇴근, 근로시간, 재택근무, 유연근무, 출장, 근태와 근무 방식 문의",
    "급여, 임금, 상여, 수당, 연봉, 퇴직금과 보수 지급 기준 문의",
    "채용, 신규 임용, 계약직, 기간제, 입사와 고용 절차 문의",
    "인사평가, 승진, 전보, 발령, 인사 시험과 인사관리 문의",
    "복지, 경조사, 의료비, 지원금, 복리후생 제도 문의",
    "복무 의무, 행동강령, 감사, 징계, 비위와 신고 관련 문의",
    "인사 업무와 직접 관련이 없거나 어느 분류에도 해당하지 않는 일반 문의",
)

_model: Any | None = None
_category_embeddings: Any | None = None
_model_lock = threading.Lock()


def _category_texts() -> tuple[str, ...]:
    """도메인 카테고리 이름과 설명을 묶어 zero-shot 비교용 문장을 만든다."""
    if len(TOPIC_CATEGORIES) != len(_DESCRIPTION_TEMPLATES):
        raise RuntimeError("TOPIC_CATEGORIES가 변경되어 임베딩 설명도 갱신해야 합니다.")
    return tuple(
        f"{category}: {description}"
        for category, description in zip(TOPIC_CATEGORIES, _DESCRIPTION_TEMPLATES, strict=True)
    )


def _load_once() -> tuple[Any, Any]:
    """SentenceTransformer와 카테고리 벡터를 프로세스당 한 번만 준비한다."""
    global _model, _category_embeddings
    if _model is not None and _category_embeddings is not None:
        return _model, _category_embeddings

    with _model_lock:
        if _model is not None and _category_embeddings is not None:
            return _model, _category_embeddings
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ProviderUnavailable(
                "임베딩 분류에는 sentence-transformers와 torch가 필요합니다. "
                "가상환경에 설치한 뒤 다시 시도해주세요."
            ) from exc

        model = SentenceTransformer(get_settings().topic_embed_model)
        category_embeddings = model.encode(
            _category_texts(),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        _model = model
        _category_embeddings = category_embeddings
        return model, category_embeddings


def _classify(message: str, model: Any, category_embeddings: Any) -> str:
    question_embedding = model.encode(
        [message],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    # 벡터를 정규화했으므로 내적은 cosine similarity와 같다.
    best_index = max(
        range(len(TOPIC_CATEGORIES)),
        key=lambda index: float(question_embedding @ category_embeddings[index]),
    )
    return TOPIC_CATEGORIES[best_index]


async def classify_by_embedding(message: str) -> str:
    """TOPIC_CATEGORIES 중 하나를 zero-shot 임베딩 유사도로 반환한다.

    모델과 카테고리 임베딩은 최초 호출 때만 로드한다. 동기식 모델 로딩과 추론은
    이벤트 루프를 막지 않도록 worker thread에서 실행한다.
    """
    if not message.strip():
        return FALLBACK_TOPIC

    model, category_embeddings = await asyncio.to_thread(_load_once)
    topic = await asyncio.to_thread(_classify, message, model, category_embeddings)
    # 방어적으로 한 번 더 확인해 도메인 밖 값이 API 계층으로 나가지 않게 한다.
    return topic if topic in TOPIC_CATEGORIES else FALLBACK_TOPIC
