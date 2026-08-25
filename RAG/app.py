from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
import mysql.connector
from mysql.connector import Error
import os
import shutil
from datetime import datetime
import uuid
from typing import List, Optional
import pydantic
from config import Config
from rag_pipeline import (
    build_vector_store_from_file,
    get_embedding_model,
    get_reranker_model,
    search_across_vector_stores,
    warm_vector_store_cache,
    select_documents_for_bulk_load,
    select_pending_documents,
)


# 모델과 FAISS 인덱스는 lifespan에서 미리 준비한다. 첫 사용자 질문이 모델 다운로드와
# 캐시 적재를 떠안지 않도록 서버가 준비 완료되기 전에 이 작업을 끝낸다.
embedding_model = None
reranker_model = None
rag_ready = False
warmed_vector_stores = 0
vector_store_warmup_failures = 0
logger = logging.getLogger("rag.startup")

def get_models():
    global embedding_model, reranker_model
    if embedding_model is None:
        embedding_model = get_embedding_model()
    if reranker_model is None:
        reranker_model = get_reranker_model()
    return embedding_model, reranker_model


@asynccontextmanager
async def lifespan(_: FastAPI):
    """모델과 로컬 FAISS 캐시를 적재한 뒤에만 RAG 요청을 받는다."""
    global rag_ready, warmed_vector_stores, vector_store_warmup_failures

    logger.info("RAG 모델 워밍업을 시작합니다.")
    try:
        active_embedding_model, _ = get_models()
        vector_root = os.path.join(Config.BASE_DIR, "vector_store")
        if Config.WARM_VECTOR_STORES:
            warmed_vector_stores, failed_stores = warm_vector_store_cache(
                vector_root,
                active_embedding_model,
            )
            vector_store_warmup_failures = len(failed_stores)
            if failed_stores:
                failed_ids = ", ".join(doc_id for doc_id, _ in failed_stores)
                logger.warning("워밍업에서 읽지 못한 FAISS 인덱스: %s", failed_ids)
        else:
            warmed_vector_stores = 0
            vector_store_warmup_failures = 0
            logger.info("FAISS 캐시 워밍업을 생략했습니다 (RAG_WARM_VECTOR_STORES=0).")

        rag_ready = True
        logger.info(
            "RAG 워밍업 완료: 모델 준비, FAISS %s개 캐시, 실패 %s개",
            warmed_vector_stores,
            vector_store_warmup_failures,
        )
    except Exception:
        logger.exception("RAG 워밍업 실패: 서버를 시작하지 않습니다.")
        raise

    yield


app = FastAPI(title=Config.API_TITLE, lifespan=lifespan)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 데이터베이스 설정
DB_CONFIG = {
    'host': Config.DB_HOST,
    'port': Config.DB_PORT,
    'user': Config.DB_USER,
    'password': Config.DB_PASSWORD,
    'database': Config.DB_NAME
}

# 파일 저장 경로
UPLOAD_DIR = Config.UPLOAD_DIR
DELETE_DIR = Config.DELETE_DIR

# 디렉토리 생성
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DELETE_DIR, exist_ok=True)

# The shared MySQL schema is owned by Django migrations.  RAG must never run
# the legacy full-schema script because it conflicts with Django's user and
# auth tables.

# 데이터베이스 연결
def get_db_connection():
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Database connection error: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")

# Pydantic 모델
class DocumentResponse(pydantic.BaseModel):
    doc_id: int
    original_file_name: str
    stored_file_name: str
    file_path: str
    created_at: str
    is_loaded: bool
    loaded_at: Optional[str]
    is_deleted: bool
    deleted_at: Optional[str]
    file_size: Optional[int] = None

def serialize_document(doc: dict) -> dict:
    """DB 조회 결과를 API 응답 형식으로 변환"""
    file_path = doc['file_path']
    if not os.path.isabs(file_path):
        file_path = os.path.join(Config.BASE_DIR, file_path)

    if os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
    elif os.path.exists(doc['file_path']):
        file_size = os.path.getsize(doc['file_path'])
    else:
        stored_path = os.path.join(UPLOAD_DIR, os.path.basename(doc['stored_file_name']))
        file_size = os.path.getsize(stored_path) if os.path.exists(stored_path) else 0

    created_at = doc['created_at']
    loaded_at = doc.get('loaded_at')
    deleted_at = doc.get('deleted_at')

    return {
        'doc_id': doc['doc_id'],
        'original_file_name': doc['original_file_name'],
        'stored_file_name': doc['stored_file_name'],
        'file_path': doc['file_path'],
        'created_at': created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at),
        'is_loaded': bool(doc['is_loaded']),
        'loaded_at': loaded_at.isoformat() if loaded_at and hasattr(loaded_at, 'isoformat') else (str(loaded_at) if loaded_at else None),
        'is_deleted': bool(doc['is_deleted']),
        'deleted_at': deleted_at.isoformat() if deleted_at and hasattr(deleted_at, 'isoformat') else (str(deleted_at) if deleted_at else None),
        'file_size': file_size,
    }

@app.get("/")
async def root():
    return {"message": "RAG Document Management API", "port": Config.API_PORT}

@app.get("/health")
async def health():
    """LLM 서비스가 RAG 프로세스의 가용성을 확인할 때 쓰는 경량 엔드포인트."""
    return {
        "status": "ok" if rag_ready else "warming",
        "models_ready": embedding_model is not None and reranker_model is not None,
        "vector_store_exists": os.path.isdir(os.path.join(Config.BASE_DIR, "vector_store")),
        "warmed_vector_stores": warmed_vector_stores,
        "vector_store_warmup_failures": vector_store_warmup_failures,
        "vector_store_cache_warmed": Config.WARM_VECTOR_STORES,
    }

@app.get("/api/documents", response_model=List[DocumentResponse])
async def get_documents():
    """삭제되지 않은 모든 문서 목록 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    try:
        query = """
            SELECT doc_id, original_file_name, stored_file_name, file_path, 
                   created_at, is_loaded, loaded_at, is_deleted, deleted_at
            FROM document 
            WHERE is_deleted = FALSE
              AND (stored_file_name LIKE 'doc_%' OR stored_file_name LIKE 'common_%')
            ORDER BY created_at DESC
        """
        cursor.execute(query)
        documents = cursor.fetchall()
        return [serialize_document(doc) for doc in documents]
    except Error as e:
        print(f"Error fetching documents: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch documents")
    finally:
        cursor.close()
        connection.close()

@app.get("/api/documents/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: int):
    """특정 문서 조회"""
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    try:
        query = """
            SELECT doc_id, original_file_name, stored_file_name, file_path, 
                   created_at, is_loaded, loaded_at, is_deleted, deleted_at
            FROM document 
            WHERE doc_id = %s
        """
        cursor.execute(query, (doc_id,))
        document = cursor.fetchone()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        return serialize_document(document)
    except Error as e:
        print(f"Error fetching document: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch document")
    finally:
        cursor.close()
        connection.close()

@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """PDF 문서 업로드"""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    file_path = None
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        # 동일한 이름의 파일이 존재하는지 확인
        check_query = "SELECT doc_id FROM document WHERE original_file_name = %s AND is_deleted = FALSE"
        cursor.execute(check_query, (file.filename,))
        existing = cursor.fetchone()
        
        if existing:
            raise HTTPException(status_code=400, detail="File with the same name already exists")
        
        # 고유한 저장 파일명 생성
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        
        # 파일명이 숫자로 시작하는지 확인 (공통 문서 구분)
        if file.filename[0].isdigit():
            stored_filename = f"common_{timestamp}_{unique_id}_{file.filename}"
        else:
            stored_filename = f"doc_{timestamp}_{unique_id}_{file.filename}"
        
        file_path = os.path.join(UPLOAD_DIR, file.filename)

        # 파일 저장
        with open(file_path, 'wb') as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 데이터베이스에 문서 정보 저장
        insert_query = """
            INSERT INTO document (original_file_name, stored_file_name, file_path, is_loaded, loaded_at)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (file.filename, stored_filename, file_path, False, None))
        connection.commit()
        
        # 저장된 문서 ID 조회
        doc_id = cursor.lastrowid
        

        # ==========================
        # 자동 Vector DB 적재
        # ==========================
        try:
            vector_path = os.path.join(Config.BASE_DIR, "vector_store", str(doc_id))
            chunk_count = build_vector_store_from_file(
                file_path,
                vector_path,
                doc_id=doc_id,
                chunk_size=Config.CHUNK_SIZE,
                chunk_overlap=Config.CHUNK_OVERLAP,
            )

            cursor.execute("""
            UPDATE document
            SET is_loaded = TRUE,
                loaded_at = %s
            WHERE doc_id = %s
            """, (datetime.now(), doc_id))

            connection.commit()
        except Exception as e:
            # Vector DB 적재 실패해도 파일 업로드는 성공으로 처리
            print(f"Vector store build failed (file still uploaded): {e}")
            chunk_count = 0




        return {
            "message": "File uploaded successfully",
            "doc_id": doc_id,
            "original_file_name": file.filename,
            "stored_file_name": stored_filename,
            "file_path": file_path,
            "chunk_count": chunk_count,
        }
    except Exception as e:
        connection.rollback()
        print(f"Error uploading document: {e}")
        import traceback
        traceback.print_exc()
        # 파일 저장 실패 시 저장된 파일 삭제
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail="Failed to upload document")
    finally:
        cursor.close()
        connection.close()

@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: int):
    """문서 삭제 (soft delete - delete 폴더로 이동)"""
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    try:
        # 문서 정보 조회
        query = "SELECT * FROM document WHERE doc_id = %s AND is_deleted = FALSE"
        cursor.execute(query, (doc_id,))
        document = cursor.fetchone()
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        
        
        # 파일을 delete 폴더로 이동
        original_path = document['file_path']

        # 상대경로 대응
        if not os.path.isabs(original_path):
            original_path = os.path.join(Config.BASE_DIR, original_path)

        filename = os.path.basename(original_path)
        delete_path = os.path.join(DELETE_DIR, filename)

        if os.path.exists(original_path):
            shutil.move(original_path, delete_path)


        # ==========================
        # Vector DB 삭제
        # ==========================

        vector_path = os.path.join(
            Config.BASE_DIR,
            "vector_store",
            str(doc_id)
        )

        if os.path.exists(vector_path):
            shutil.rmtree(vector_path)
            print(f"Vector store deleted: {vector_path}")


        # 데이터베이스 업데이트
        update_query = """
            UPDATE document 
            SET is_deleted = TRUE,
                deleted_at = %s,
                file_path = %s,
                is_loaded = FALSE,
                loaded_at = NULL
            WHERE doc_id = %s
        """


        cursor.execute(update_query, (datetime.now(), delete_path, doc_id))
        connection.commit()
        
        return {"message": "Document deleted successfully", "doc_id": doc_id}
    except Error as e:
        connection.rollback()
        print(f"Error deleting document: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete document")
    finally:
        cursor.close()
        connection.close()

@app.put("/api/documents/{doc_id}/load")
async def load_document_to_vector(doc_id: int):
    """문서를 벡터 DB에 적재"""
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        query = """
            SELECT *
            FROM document
            WHERE doc_id = %s
            AND is_deleted = FALSE
        """

        cursor.execute(query, (doc_id,))
        document = cursor.fetchone()

        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        file_path = document["file_path"]
        if not os.path.isabs(file_path):
            file_path = os.path.join(Config.BASE_DIR, file_path)

        vector_path = os.path.join(Config.BASE_DIR, "vector_store", str(doc_id))
        chunk_count = build_vector_store_from_file(
            file_path,
            vector_path,
            doc_id=doc_id,
            chunk_size=Config.CHUNK_SIZE,
            chunk_overlap=Config.CHUNK_OVERLAP,
        )

        update_query = """
            UPDATE document
            SET is_loaded = TRUE,
                loaded_at = %s
            WHERE doc_id = %s
        """

        cursor.execute(update_query, (datetime.now(), doc_id))
        connection.commit()

        return {
            "message": "Vector DB loading completed",
            "doc_id": doc_id,
            "chunk_count": chunk_count,
        }
    except Exception as e:
        connection.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        connection.close()


@app.post("/api/documents/load-all")
async def load_all_documents(mode: str = "skip"):
    """미적재 문서 전체를 벡터 DB에 적재 (skip/overwrite)"""
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        query = """
            SELECT doc_id, original_file_name, stored_file_name, file_path, created_at,
                   is_loaded, loaded_at, is_deleted, deleted_at
            FROM document
            WHERE is_deleted = FALSE
            ORDER BY created_at ASC
        """
        cursor.execute(query)
        documents = cursor.fetchall()

        selected_documents = select_documents_for_bulk_load(documents, mode=mode)
        if not selected_documents:
            return {"message": "No documents selected", "loaded_count": 0, "failed": [], "mode": mode}

        loaded_ids = []
        failed = []

        for document in selected_documents:
            doc_id = document["doc_id"]
            file_path = document["file_path"]
            if not os.path.isabs(file_path):
                file_path = os.path.join(Config.BASE_DIR, file_path)

            vector_path = os.path.join(Config.BASE_DIR, "vector_store", str(doc_id))
            try:
                chunk_count = build_vector_store_from_file(
                    file_path,
                    vector_path,
                    doc_id=doc_id,
                    chunk_size=Config.CHUNK_SIZE,
                    chunk_overlap=Config.CHUNK_OVERLAP,
                )
                cursor.execute(
                    """
                    UPDATE document
                    SET is_loaded = TRUE,
                        loaded_at = %s
                    WHERE doc_id = %s
                    """,
                    (datetime.now(), doc_id),
                )
                connection.commit()
                loaded_ids.append({"doc_id": doc_id, "chunk_count": chunk_count})
            except Exception as exc:
                connection.rollback()
                failed.append({"doc_id": doc_id, "error": str(exc)})

        return {
            "message": "Bulk vector loading completed",
            "loaded_count": len(loaded_ids),
            "loaded_ids": loaded_ids,
            "failed": failed,
            "mode": mode,
        }
    except Exception as e:
        connection.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        connection.close()

@app.get("/api/documents/{doc_id}/file")
async def get_document_file(doc_id: int):
    """문서 파일 반환 (PDF 뷰어용)"""
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    try:
        query = """
            SELECT file_path, stored_file_name, original_file_name
            FROM document
            WHERE doc_id = %s AND is_deleted = FALSE
        """
        cursor.execute(query, (doc_id,))
        document = cursor.fetchone()
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        file_path = document['file_path']
        if not os.path.isabs(file_path):
            file_path = os.path.join(Config.BASE_DIR, file_path)
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")
        
        return FileResponse(
            file_path,
            media_type='application/pdf',
            filename=document['original_file_name']
        )
    except Error as e:
        print(f"Error fetching document file: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch document file")
    finally:
        cursor.close()
        connection.close()







from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    # doc_id: int


@app.post("/api/search")
async def search_vector(request: SearchRequest):

    try:
        query = " ".join((request.query or "").split())
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")

        vector_root = os.path.join(Config.BASE_DIR, "vector_store")
        if not os.path.exists(vector_root):
            raise HTTPException(status_code=404, detail="No vector store found")

        # startup에서 워밍업된 인스턴스를 재사용한다.
        active_embedding_model, active_reranker_model = get_models()

        results = search_across_vector_stores(
            query,
            vector_root,
            active_embedding_model,
            active_reranker_model,
            top_k=Config.SEARCH_TOP_K,
            initial_candidates=Config.SEARCH_INITIAL_CANDIDATES,
        )

        if not results:
            raise HTTPException(status_code=404, detail="No relevant document found")

        return {
            "query": query,
            "results": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))






# 정적 파일 서빙 (API 라우트 등록 후 마지막에 mount)
# 정적 파일 서빙
app.mount("/res", StaticFiles(directory="res"), name="res")
app.mount("/", StaticFiles(directory=".", html=True), name="static")

print("========== ROUTES ==========")
for route in app.routes:
    print(route.path)
print("============================")



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=Config.API_HOST, port=Config.API_PORT)



