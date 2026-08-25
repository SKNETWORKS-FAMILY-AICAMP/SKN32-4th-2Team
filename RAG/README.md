# Smart HR RAG Service

사내 HR 규정 PDF를 MySQL 문서 목록과 문서별 FAISS 인덱스로 관리하고 검색하는 FastAPI 서비스입니다.
이 서비스는 Django로 이관하지 않습니다. Django WEB은 사용자·채팅·세션을 담당하고, RAG는 FastAPI로 독립 실행되어 LLM이 HTTP로 호출합니다.

팀원이 새 환경에서 처음 실행하는 절차와 이후의 일반 실행 절차는 [SETUP.md](SETUP.md)를 기준으로 합니다.

첫 PDF 부트스트랩이 성공한 같은 PC·같은 DB에서는 이후 `python app.py`로 RAG 서버만 다시 실행하면 됩니다. 새 PC, 새 DB, 삭제된 `vector_store`, 새 PDF, 파이프라인 설정 변경 시에만 부트스트랩 또는 재색인이 다시 필요합니다.

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
RAG_CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
~~~

서버는 모델과 FAISS 캐시 워밍업이 끝난 뒤에만 `Application startup complete`를 출력합니다. 처음 기동할 때는 모델 다운로드·메모리 적재 때문에 시간이 걸릴 수 있으므로, 이 로그와 `/health`의 `models_ready: true`를 확인한 뒤 LLM과 Django를 실행합니다. 기본 `RAG_WARM_VECTOR_STORES=1`은 문서별 FAISS 캐시도 미리 읽어 첫 질문 지연을 없앱니다.

서버가 뜨면 http://127.0.0.1:8001/docs 에서 API 문서를, /health에서 프로세스 상태를 확인할 수 있습니다.

## MySQL 초기화와 문서 부트스트랩

공유 MySQL 스키마는 Django 마이그레이션이 소유합니다. RAG는 시작할 때 테이블을 자동 생성하지 않습니다.

```powershell
cd ..\web
.\.venv-django\Scripts\python.exe manage.py migrate --noinput

cd ..\RAG
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply
```

`bootstrap_documents.py`는 `res/pdf`의 PDF를 모두 `document`에 비파괴적으로 등록하고 FAISS 인덱스까지 만든다. 기본 실행은 미리보기이며, `--apply`일 때만 실제 쓰기가 일어난다. 중단된 경우 같은 명령을 다시 실행하면 적재되지 않은 문서부터 이어서 처리한다.

`RAG/sql/rag_document.sql`은 과거의 고정 코퍼스용 파일로 `TRUNCATE TABLE document`를 포함한다. 현재 초기화에는 사용하지 않는다. `POST /api/documents/load-all`도 이미 등록된 DB 행만 색인하므로, PDF를 폴더에 복사한 뒤 최초 등록 용도로 사용하면 안 된다.

자세한 팀별 설정, 서버 기동 순서, 재색인 조건과 문제 해결은 [SETUP.md](SETUP.md)를 참고한다.

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
| Django WEB | http://127.0.0.1:8000 |
| LLM FastAPI | http://127.0.0.1:8002 |
| RAG FastAPI | http://127.0.0.1:8001 |

이 조합에서는 RAG/.env의 RAG_API_PORT=8001, LLM/.env의 RAG_BASE_URL=http://127.0.0.1:8001, Django의 DOC_API_BASE_URL=http://127.0.0.1:8001로 맞춥니다.

## Git 정책

커밋 대상은 운영 코드, API 문서, .env.example, 검수된 기본 PDF 코퍼스입니다. 다음은 Git에 넣지 않습니다.

- 실제 .env와 DB 자격 증명
- 가상환경, 캐시, 로그, 임시 PDF
- vector_store, vector_store_backup, qdrant_data
- 검색 랭킹 테스트 원본 응답, 압축 백업
- django_rag/와 run_django_rag.py 같은 FastAPI-to-Django 비교 실험본

기존에 이미 추적된 임시 PDF·랭킹 테스트 응답은 이 브랜치에서 Git 추적만 해제합니다. 로컬 파일은 삭제하지 않습니다.
