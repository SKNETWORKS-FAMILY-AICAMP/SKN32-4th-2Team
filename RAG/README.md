# Smart HR RAG Service

사내 HR 규정 PDF를 새 MySQL `rag_chatbot_v4`의 문서 목록과 문서별 FAISS 인덱스로 관리하고 검색하는 FastAPI 서비스입니다.
이 서비스는 Django로 이관하지 않습니다. Django WEB은 사용자·채팅·세션을 담당하고, RAG는 FastAPI로 독립 실행되어 LLM이 HTTP로 호출합니다.

팀원이 새 환경에서 처음 실행하는 절차와 이후의 일반 실행 절차는 [SETUP.md](../SETUP.md)를 기준으로 합니다.

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

전체 스택(web·rag·llm·nginx)을 한 번에 띄우는 Docker Compose 배포는 레포 루트에서 실행하며, 그 절차는 루트 README와 [SETUP.md](../SETUP.md)를 따릅니다. 아래는 컨테이너 없이 RAG만 로컬(venv)에서 직접 실행하는 절차입니다.

## 준비

Python 3.11과 MySQL 8을 권장합니다. 실제 DB 자격 증명은 코드에 넣지 말고 RAG/.env에만 둡니다.

~~~powershell
cd D:\Dev_Tools\SKN32-4th-2Team\RAG
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
RAG_DB_NAME=rag_chatbot_v4
RAG_CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
~~~

`RAG_DB_HOST`·`RAG_DB_PORT`·`RAG_DB_NAME`은 `web/.env`의 `DATABASE_URL`과 같은 **새 운영 대상**을 가리켜야 합니다. 레거시 이관 원본 `LEGACY_DATABASE_URL`은 WEB 이관 도구에서만 쓰며 RAG/.env에는 넣지 않습니다.

서버는 모델과 FAISS 캐시 워밍업이 끝난 뒤에만 `Application startup complete`를 출력합니다. 처음 기동할 때는 모델 다운로드·메모리 적재 때문에 시간이 걸릴 수 있으므로, 이 로그와 `/health`의 `models_ready: true`를 확인한 뒤 LLM과 Django를 실행합니다. 기본 `RAG_WARM_VECTOR_STORES=1`은 문서별 FAISS 캐시도 미리 읽어 첫 질문 지연을 없앱니다.

서버가 뜨면 http://127.0.0.1:8001/docs 에서 API 문서를, /health에서 프로세스 상태를 확인할 수 있습니다.

## 새 RAG 초기화와 문서 부트스트랩

모든 팀원은 새 MySQL `rag_chatbot_v4`와 현재 프로젝트의 PDF 코퍼스에서 RAG를 새로 시작합니다. RAG 절차에는 기존 `document` 행·PDF·FAISS 인덱스를 이관하는 단계가 없습니다. `chat_source`는 과거 LLM 답변에 표시된 파일명·페이지를 보존하는 채팅 근거 스냅샷으로 WEB 이관 범위이며, PDF를 등록하거나 RAG 검색 인덱스를 만드는 데 사용하지 않습니다. 공유 MySQL 스키마는 Django 마이그레이션이 소유하며, RAG는 시작할 때 테이블을 자동 생성하지 않습니다.

### 첫 부트스트랩 전 `vector_store` 확인

`RAG/vector_store`는 PC별 런타임 파일입니다. 폴더가 이미 있다면 이전 실행의 인덱스를 새 환경에 재사용하지 않도록, 첫 부트스트랩 전에 **사용자가 직접** 안전한 백업 위치로 옮기거나 정리해 빈 상태로 만듭니다. 이 스크립트는 기존·고아 `vector_store/<doc_id>`를 자동 삭제하지 않습니다.

이 확인이 필요한 이유는 기본 `skip` 모드가 유효한 기존 `vector_store/<doc_id>`를 발견하면 새로 만들지 않고 상태만 복구할 수 있기 때문입니다. 즉 새 시작에서는 DB와 PDF뿐 아니라 로컬 `vector_store`도 의도적으로 깨끗한 상태여야 합니다.

### 모든 팀원의 첫 실행

```powershell
cd ..\web
.\.venv-django\Scripts\python.exe manage.py migrate --noinput

cd ..\RAG
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply
```

`bootstrap_documents.py`는 `RAG_UPLOAD_DIR` 바로 아래의 PDF(기본값: `RAG/res/pdf`)만 스캔해 새 `document` 행에 등록하고 문서별 FAISS 인덱스를 만듭니다. 레거시 프로젝트 폴더는 자동으로 읽지 않습니다. 기본 실행은 미리보기이며, `--apply`일 때만 실제 쓰기가 일어납니다. 중단된 경우 같은 명령을 다시 실행하면 적재되지 않은 문서부터 이어서 처리합니다.

첫 부트스트랩에는 합의된 현재 PDF 코퍼스만 둡니다. 이 도구는 PDF 내용 해시로 동일성을 판별하지 않고 활성 문서의 파일 경로·파일명을 사용합니다. 같은 파일명으로 내용을 교체하는 경우에는 새 문서로 간주하지 말고 `--mode overwrite`로 재색인하고, 다른 문서라면 먼저 파일명을 바꾼 뒤 등록합니다.

이미 정상 초기화가 끝난 뒤 PDF 내용을 교체했거나, 청킹·임베딩 모델·조문 머리 설정을 바꾼 경우에만 `--mode overwrite`로 다시 색인합니다. 이 모드는 현재 PDF로 임시 FAISS 인덱스를 완성한 뒤에만 기존 `vector_store/<doc_id>`를 교체하고, 교체 실패 시 기존 인덱스를 복구합니다.

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply --mode overwrite
```

`RAG/sql/rag_document.sql`은 과거의 고정 코퍼스용 파일로 `TRUNCATE TABLE document`를 포함한다. 현재 초기화에는 사용하지 않는다. `POST /api/documents/load-all`도 이미 등록된 DB 행만 색인하므로, PDF를 폴더에 복사한 뒤 최초 등록 용도로 사용하면 안 된다.

자세한 팀별 설정, 서버 기동 순서, 재색인 조건과 문제 해결은 [SETUP.md](../SETUP.md)를 참고한다.

## API

현재 스택에서 실제로 호출되는 엔드포인트만 정리했습니다. 호출자는 두 곳입니다 — Django 관리자 문서 화면이 로드하는 `web/static/js/rag.js`(브라우저 → nginx `/rag/`)와 LLM 서비스(`rag_client.py`).

| Method | Path | 호출자 | 용도 |
| --- | --- | --- | --- |
| GET | /health | LLM | 경량 상태 점검(up/down 표시) |
| GET | /api/documents | 관리자 화면(rag.js) | 활성 문서 목록 |
| POST | /api/documents/upload | 관리자 화면(rag.js) | PDF 업로드 및 자동 인덱싱 |
| DELETE | /api/documents/{doc_id} | 관리자 화면(rag.js) | 문서 소프트 삭제 |
| PUT | /api/documents/{doc_id}/load | 관리자 화면(rag.js) | 단일 문서 재적재 |
| POST | /api/documents/load-all?mode=skip | 관리자 화면(rag.js) | 미적재 문서만 적재 |
| POST | /api/documents/load-all?mode=overwrite | 관리자 화면(rag.js) | 대상 문서 인덱스를 다시 생성 |
| GET | /api/documents/{doc_id}/file | 관리자 화면(rag.js) | PDF 원본 반환 (뷰어용) |
| POST | /api/search | LLM | 검색 (일반 채팅 흐름의 핵심 호출) |

`GET /`(정적 루트 마운트)와 `GET /api/documents/{doc_id}`(문서 상세)는 RAG에 구현돼 있지만 현재 Django·LLM 어느 쪽도 호출하지 않습니다.

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

기본 `RAG_DEVICE=auto`는 PyTorch CUDA 가능 여부에 따라 cuda 또는 cpu를 자동 선택합니다.

| 값 | 동작 |
| --- | --- |
| `auto` 또는 비움 | CUDA 가능 시 cuda, 아니면 cpu |
| cpu | CPU 강제 |
| cuda | CUDA 강제; CUDA PyTorch가 없으면 오류로 설정 문제를 드러냄 |

로그와 `/health`의 `backend=faiss`, `device`, `search_initial_candidates=20`을 확인합니다. GPU가 장착되어 있어도 CPU 전용 PyTorch가 설치되어 있으면 GPU는 사용되지 않습니다.

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
- 빌드·테스트 로그(예: rag-build-test.log, compose-test.log)와 컨테이너 임시 산출물

기존에 이미 추적된 임시 PDF·랭킹 테스트 응답은 이 브랜치에서 Git 추적만 해제합니다. 로컬 파일은 삭제하지 않습니다.
