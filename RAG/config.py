"""RAG 서비스 설정.

실제 DB 자격 증명은 RAG/.env 또는 프로세스 환경변수에서만 읽는다.
기본값에 팀원 PC의 계정·비밀번호를 넣지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR / ".env")


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def _csv_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # API
    API_HOST = os.getenv("RAG_API_HOST", "0.0.0.0")
    API_PORT = _int_env("RAG_API_PORT", 8001)
    API_TITLE = "RAG Document Management API"

    # MySQL
    DB_HOST = os.getenv("RAG_DB_HOST", "127.0.0.1")
    DB_PORT = _int_env("RAG_DB_PORT", 3306)
    DB_USER = os.getenv("RAG_DB_USER", "")
    DB_PASSWORD = os.getenv("RAG_DB_PASSWORD", "")
    DB_NAME = os.getenv("RAG_DB_NAME", "rag_chatbot")

    # Files and local FAISS indexes
    BASE_DIR = str(_BASE_DIR)
    UPLOAD_DIR = os.getenv("RAG_UPLOAD_DIR", str(_BASE_DIR / "res" / "pdf"))
    DELETE_DIR = os.getenv("RAG_DELETE_DIR", str(Path(UPLOAD_DIR) / "delete"))

    # Browser clients. Production should list only trusted origins.
    CORS_ORIGINS = _csv_env(
        "RAG_CORS_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000",
    )

    # Upload limits
    MAX_FILE_SIZE = _int_env("RAG_MAX_FILE_SIZE", 50 * 1024 * 1024)
    ALLOWED_EXTENSIONS = [".pdf"]

    # Retrieval quality settings
    CHUNK_SIZE = _int_env("RAG_CHUNK_SIZE", 400)
    CHUNK_OVERLAP = _int_env("RAG_CHUNK_OVERLAP", 80)
    MIN_CHUNK_LENGTH = _int_env("RAG_MIN_CHUNK_LENGTH", 80)
    EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask")
    RERANKER_MODEL = os.getenv("RAG_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
    # 첫 질의가 모델·FAISS 적재를 떠안지 않도록 기본적으로 서버 기동 중 캐시한다.
    WARM_VECTOR_STORES = _bool_env("RAG_WARM_VECTOR_STORES", True)
    SEARCH_TOP_K = _int_env("RAG_SEARCH_TOP_K", 5)
    SEARCH_INITIAL_CANDIDATES = _int_env("RAG_SEARCH_INITIAL_CANDIDATES", 20)
