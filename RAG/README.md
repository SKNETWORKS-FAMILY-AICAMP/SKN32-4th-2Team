# Smart HR RAG Service

사내 HR 규정 PDF를 MySQL 문서 목록과 문서별 FAISS 인덱스로 관리하고 검색하는 FastAPI 서비스입니다.
이 서비스는 Django로 이관하지 않습니다. Django WEB은 사용자·채팅·세션을 담당하고, RAG는 FastAPI로 독립 실행되어 LLM이 HTTP로 호출합니다.

~~~text
Django WEB  →  LLM FastAPI  →  RAG FastAPI
                                  ├─ MySQL: document 메타데이터
                                  ├─ PDF 원본
                                  └─ FAISS: vector_store/<doc_id>
~~~

## 현재 런타임 범위

- 문서 관리 API: 업로드, 조회, 소프트 삭제, 개별·전체 인덱스 적재
- 검색 API: 문서별 FAISS 검색, BM25 보조 점수, CrossEncoder 재정렬
- 최신 고도화: 조문 머리 보강, 요청당 질문 임베딩 1회, FAISS 스토어 캐시, CPU/GPU 선택
- 벡터 인덱스는 Git에 저장하지 않습니다. 문서 DB 행·PDF 원본·vector_store/<doc_id>가 같은 시점의 한 묶음입니다.

## 준비

Python 3.11과 MySQL 8을 권장합니다. 실제 DB 자격 증명은 코드에 넣지 말고 RAG/.env에만 둡니다.

~~~powershell
cd D:\SKN32-4th-2Team\RAG
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
~~~

최소 환경 예시는 다음과 같습니다.

~~~dotenv
RAG_API_PORT=8001
RAG_DB_HOST=127.0.0.1
RAG_DB_PORT=3306
RAG_DB_USER=실제_계정
RAG_DB_PASSWORD=실제_비밀번호
RAG_DB_NAME=rag_chatbot
RAG_CORS_ORIGINS=http://127.0.0.1:8100,http://localhost:8100
~~~

서버가 뜨면 http://127.0.0.1:8001/docs 에서 API 문서를, /health에서 프로세스 상태를 확인할 수 있습니다.

## MySQL 초기화와 문서 시드

리포지터리 루트의 sql/rag_chatbot_schema.sql은 스키마 생성용입니다. RAG/app.py도 같은 경로를 읽어 테이블이 없을 때 생성합니다.

RAG/sql/rag_document.sql은 초기 PDF 26건을 넣기 위한 개발 초기화 스크립트입니다. 이 파일에는 TRUNCATE TABLE document가 포함되어 있습니다.

> 공유·스테이징·운영 MySQL에는 rag_document.sql을 실행하지 마세요. 기존 문서 행과 인덱스가 모두 끊어질 수 있습니다.

새 로컬 DB만 초기화할 때의 순서:

1. MySQL 스키마를 생성합니다.
2. document 테이블이 비어 있는 새 로컬 DB에서만 RAG/sql/rag_document.sql을 실행합니다.
3. 관리 화면 또는 POST /api/documents/load-all?mode=overwrite로 PDF를 인덱싱합니다.
4. 검색 API로 문서명·페이지·조문 머리가 맞는지 확인합니다.

이미 운영 중인 DB는 DB 행, PDF 원본, vector_store를 먼저 백업하고 대상 환경에서만 재적재합니다.

## API

| Method | Path | 용도 |
| --- | --- | --- |
| GET | /health | LLM이 확인하는 경량 상태 점검 |
| GET | /api/documents | 활성 문서 목록 |
| POST | /api/documents/upload | PDF 업로드 및 자동 인덱싱 |
| PUT | /api/documents/{doc_id}/load | 단일 문서 재적재 |
| POST | /api/documents/load-all?mode=skip | 미적재 문서만 적재 |
| POST | /api/documents/load-all?mode=overwrite | 대상 문서 인덱스를 다시 생성 |
| POST | /api/search | LLM이 호출하는 검색 API |

전체 재적재는 해당 MySQL·PDF·vector_store 묶음이 명확한 환경에서만 수행합니다. 다른 PC 또는 다른 DB에서 만든 vector_store를 복사하면 doc_id가 달라 잘못된 문서가 검색될 수 있습니다.

## 인덱스 고도화 후 재적재

rag_pipeline.py의 청킹·조문 머리·임베딩 모델이 바뀌어도 기존 FAISS 인덱스는 자동으로 변환되지 않습니다. 특히 RAG_ARTICLE_HEAD, RAG_CHUNK_SIZE, RAG_CHUNK_OVERLAP, 임베딩 모델을 변경했다면 대상 문서를 overwrite로 재적재해야 합니다.

재적재 전후에 다음을 기록합니다.

- 대상 DB와 문서 ID 목록
- PDF 원본과 vector_store 백업 위치
- 파이프라인 설정값과 Git 커밋
- 대표 질문의 검색 시간, 문서명, 페이지, 조문 인용 정확성

컨테이너·배포 환경에서는 PDF와 vector_store에 영속 볼륨 또는 외부 저장소를 연결해야 합니다. DB만 복구하면 검색 인덱스는 복구되지 않습니다.

## CPU/GPU 성능 테스트

RAG_DEVICE를 지정하지 않으면 PyTorch CUDA 가능 여부에 따라 cuda 또는 cpu를 자동 선택합니다.

| 값 | 동작 |
| --- | --- |
| 비움 | CUDA 가능 시 cuda, 아니면 cpu |
| cpu | CPU 강제 |
| cuda | CUDA 강제; CUDA PyTorch가 없으면 오류로 설정 문제를 드러냄 |

로그에 embedding model device=...와 reranker device=...가 표시되는지 확인합니다. GPU가 장착되어 있어도 CPU 전용 PyTorch가 설치되어 있으면 GPU는 사용되지 않습니다.

성능 비교는 같은 문서 인덱스와 같은 질문 세트에서 CPU와 GPU를 각각 콜드 1회·웜 캐시 여러 회 측정해 검색 시간과 전체 LLM 응답 시간을 분리해 기록합니다.

## 4차 프로젝트 로컬 연동

| 서비스 | 주소 |
| --- | --- |
| Django WEB | http://127.0.0.1:8100 |
| LLM FastAPI | http://127.0.0.1:8102 |
| RAG FastAPI | http://127.0.0.1:8101 |

이 조합에서는 RAG/.env의 RAG_API_PORT=8101, LLM/.env의 RAG_BASE_URL=http://127.0.0.1:8101, Django의 DOC_API_BASE_URL=http://127.0.0.1:8101로 맞춥니다.

## Git 정책

커밋 대상은 운영 코드, API 문서, .env.example, 검수된 기본 PDF 코퍼스입니다. 다음은 Git에 넣지 않습니다.

- 실제 .env와 DB 자격 증명
- 가상환경, 캐시, 로그, 임시 PDF
- vector_store, vector_store_backup, qdrant_data
- 검색 랭킹 테스트 원본 응답, 압축 백업
- django_rag/와 run_django_rag.py 같은 FastAPI-to-Django 비교 실험본

기존에 이미 추적된 임시 PDF·랭킹 테스트 응답은 이 브랜치에서 Git 추적만 해제합니다. 로컬 파일은 삭제하지 않습니다.
