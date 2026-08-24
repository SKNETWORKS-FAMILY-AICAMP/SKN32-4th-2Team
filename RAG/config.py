# RAG 시스템 설정
import os

class Config:
    # API 설정
    API_HOST = "0.0.0.0"
    API_PORT = 8001
    API_TITLE = "RAG Document Management API"
    
    # 데이터베이스 설정
    DB_HOST = "localhost"
    DB_PORT = 3306
    DB_USER = "root"
    DB_PASSWORD = "1234"  # 필요시 비밀번호 설정
    DB_NAME = "rag_chatbot"
    
    # 파일 저장 경로
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_DIR = os.path.join(BASE_DIR, "res", "pdf")
    DELETE_DIR = os.path.join(UPLOAD_DIR, "delete")
    
    # CORS 설정
    CORS_ORIGINS = ["*"]  # 개발용 - 프로덕션에서는 특정 도메인으로 제한
    
    # 파일 업로드 제한
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS = [".pdf"]
    
    # 벡터 DB 설정 (추후 RAG 연동시 사용)
    VECTOR_DB_HOST = "localhost"
    VECTOR_DB_PORT = 6333  # Qdrant 기본 포트
    VECTOR_DB_COLLECTION = "rag_documents"

    # RAG 품질 관리 설정
    CHUNK_SIZE = 400
    CHUNK_OVERLAP = 80
    MIN_CHUNK_LENGTH = 80
    EMBEDDING_MODEL = "jhgan/ko-sroberta-multitask"
    RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
    SEARCH_TOP_K = 5
    SEARCH_INITIAL_CANDIDATES = 20
