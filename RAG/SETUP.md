# 팀 공용 로컬 실행 가이드

이 문서는 Django WEB, LLM, RAG를 MySQL과 함께 처음 실행하는 방법과 이후의 일반 실행 방법을 정리한 기준 문서입니다.

```text
Django WEB (8000) → LLM (8002) → RAG (8001)
                                      ├─ MySQL: document 메타데이터
                                      ├─ RAG/res/pdf: 원본 PDF
                                      └─ RAG/vector_store: 이 PC의 FAISS 인덱스
```

## 먼저 알아둘 점

- 공유 MySQL의 테이블은 Django의 `manage.py migrate`가 만든다. RAG가 스키마를 자동 생성하지 않는다.
- `RAG/res/pdf`에 PDF를 복사하는 것만으로는 검색 대상이 되지 않는다. PDF마다 `document` 행과 `vector_store/<doc_id>` 인덱스가 필요하다.
- `vector_store`는 Git에 넣지 않는 PC별 런타임 파일이다. 따라서 같은 MySQL을 공유해도 새 PC에서는 한 번씩 인덱스를 만들어야 한다.
- 현재 로컬 PDF 폴더에는 93개 PDF가 있다. 그중 Git에 아직 추가되지 않은 PDF가 있다면, 팀원이 같은 코퍼스로 실행하기 전에 해당 PDF를 커밋하거나 별도 공유해야 한다. 이 스크립트는 없는 PDF를 내려받지 않는다.
- 실제 `.env`, DB 비밀번호, API 키, `vector_store`는 커밋하지 않는다.

## 0. 준비물

- Python 3.11
- MySQL 8 이상과 접근 가능한 빈 데이터베이스 `rag_chatbot`
- Git으로 받은 프로젝트와 팀에서 합의한 PDF 코퍼스
- 실제 LLM을 시험할 경우 OpenAI 또는 Gemini API 키

데이터베이스가 아직 없다면 **한 번만** 빈 DB를 만든다. 기존 DB를 삭제하거나 다시 만들지 않는다.

```sql
CREATE DATABASE rag_chatbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

## 1. 팀원별 가상환경·환경변수 준비

PowerShell에서 각 서비스의 가상환경과 `.env`를 준비한다. 실제 값은 팀 내부의 안전한 경로로만 공유한다.

```powershell
cd D:\SKN32-4th-2Team\web
py -3.11 -m venv .venv-django
.\.venv-django\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env

cd ..\RAG
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env

cd ..\LLM
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

세 `.env`는 다음 관계를 만족해야 한다.

| 파일 | 확인할 값 |
| --- | --- |
| `web/.env` | `DATABASE_URL`의 DB명이 `rag_chatbot`, `CHAT_API_BASE_URL=http://127.0.0.1:8002`, `DOC_API_BASE_URL=http://127.0.0.1:8001` |
| `RAG/.env` | `RAG_DB_*`가 위와 같은 MySQL의 `rag_chatbot`, `RAG_API_PORT=8001` |
| `LLM/.env` | `RAG_BASE_URL=http://127.0.0.1:8001`, 실제 테스트라면 LLM API 키 |

CPU/GPU 비교를 할 때만 `RAG/.env`에 `RAG_DEVICE=cpu` 또는 `RAG_DEVICE=cuda`를 명시한다. 빈 값은 자동 선택이다.

기본 `RAG_WARM_VECTOR_STORES=1`은 RAG 기동 중 임베딩·리랭커 모델과 FAISS 캐시를 미리 적재한다. 따라서 처음 서버를 켤 때는 시간이 더 걸리지만, 첫 채팅이 모델 로딩 때문에 실패하지 않는다. 메모리가 매우 부족한 PC에서만 `0`으로 바꾸며, 그 경우 첫 검색이 느려질 수 있다.

## 2. 첫 실행: DB 마이그레이션과 PDF 초기화

초기화 중에는 RAG 서버를 끈 상태를 권장한다. MySQL은 실행 중이어야 한다.

### 2-1. Django 마이그레이션

```powershell
cd D:\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py migrate --noinput
```

이 명령이 `document`를 포함한 공용 테이블을 만든다. 다음 레거시 파일은 실행하지 않는다.

- `RAG/sql/rag_document.sql`: `TRUNCATE TABLE document`를 수행하고 고정된 일부 PDF만 등록한다.
- 예전 `rag_chatbot_schema.sql`: 현재 공용 스키마와 충돌할 수 있다.

### 2-2. PDF 등록·FAISS 색인

`bootstrap_documents.py`는 `RAG/res/pdf` 바로 아래의 모든 PDF를 스캔한다. 새 문서 행을 만들고, 문서별 FAISS 인덱스를 생성한다. 기본 실행은 **쓰기 없는 미리보기**다.

```powershell
cd D:\SKN32-4th-2Team\RAG
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py
```

출력의 PDF 개수와 대상 DB를 확인한 뒤 실제 초기화를 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply
```

특성:

- 기존 `document` 행을 지우지 않는다.
- PDF 하나마다 DB 행을 먼저 커밋하므로, 중단되거나 일부 PDF가 실패해도 같은 명령으로 재실행하면 이어서 처리한다.
- 성공한 임시 FAISS 인덱스만 `vector_store/<doc_id>`로 교체한다.
- 실패한 문서는 `is_loaded=FALSE`로 남으며, 오류를 해결한 뒤 다시 실행하면 된다.
- 최초 실행에서는 `POST /api/documents/load-all`을 별도로 실행할 필요가 없다. 이 스크립트가 등록과 색인을 모두 처리한다.

이미 정상 색인이 있는 문서는 기본값에서 건너뛴다. 청킹·임베딩 모델·조문 머리 설정을 바꾼 뒤 전체를 다시 만들 때만 다음 명령을 사용한다.

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply --mode overwrite
```

`overwrite`는 대상 PDF의 기존 인덱스를 성공적으로 새로 만든 후 교체한다. 성능 비교 전에는 대상 PDF, Git 커밋, RAG 설정값을 함께 기록한다.

### 2-3. 초기화 검증

RAG를 시작한다.

```powershell
cd D:\SKN32-4th-2Team\RAG
.\.venv\Scripts\python.exe app.py
```

`Application startup complete`와 `RAG 워밍업 완료` 로그가 나온 뒤에 LLM·Django를 시작한다. `/health` 응답에서 `models_ready: true`, `warmed_vector_stores`를 확인할 수 있다.

새 PowerShell 창에서 상태와 문서 목록을 확인한다.

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8001/api/documents
```

`/api/documents`의 모든 초기 대상 문서가 `is_loaded: true`인지 확인한다. 검색은 Swagger UI `http://127.0.0.1:8001/docs`의 `POST /api/search` 또는 다음 명령으로 확인한다.

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8001/api/search `
  -ContentType 'application/json' `
  -Body '{"query":"연차휴가 규정을 알려줘"}'
```

## 3. 이후의 일반 실행

초기화가 성공한 뒤에는 PDF 부트스트랩을 다시 실행할 필요가 없다. MySQL을 실행한 뒤 아래 순서로 세 서버만 켠다.

### 창 1 — RAG

```powershell
cd D:\SKN32-4th-2Team\RAG
.\.venv\Scripts\python.exe app.py
```

### 창 2 — LLM

```powershell
cd D:\SKN32-4th-2Team\LLM
.\.venv\Scripts\python.exe -m app.main
```

### 창 3 — Django WEB

```powershell
cd D:\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

브라우저에서 `http://127.0.0.1:8000`으로 접속한다. 종료는 각 창에서 `Ctrl+C`를 누른다.

## 4. 언제 다시 부트스트랩해야 하나

| 상황 | 실행할 명령 |
| --- | --- |
| 새 PC 또는 새 로컬 MySQL | `bootstrap_documents.py --apply` |
| `vector_store`를 지웠거나 새로 받은 환경 | `bootstrap_documents.py --apply` |
| PDF를 폴더에 직접 추가 | `bootstrap_documents.py --apply` |
| PDF 한 개를 관리자 화면에서 업로드 | 별도 부트스트랩 불필요 — 업로드가 자동 색인 |
| 청킹·임베딩 모델·조문 머리 설정 변경 | `bootstrap_documents.py --apply --mode overwrite` |

공유 MySQL을 여러 PC가 쓸 경우에는 한 명이 Django 마이그레이션과 문서 행 등록을 완료하면 된다. 단, 각 PC의 `vector_store`는 로컬이므로 각 팀원이 자신의 PC에서 한 번씩 부트스트랩을 실행해야 한다. 스크립트는 같은 파일명의 활성 문서 행을 재사용한다.

## 5. 자주 발생하는 문제

| 증상 | 원인과 조치 |
| --- | --- |
| `No vector store found` | 이 PC의 `RAG/vector_store`가 없다. 부트스트랩을 실행한다. |
| `document 테이블을 읽을 수 없습니다` | Django 마이그레이션 전이다. `web/manage.py migrate --noinput`을 실행한다. |
| PDF를 넣었는데 `load-all`이 0건 | PDF 파일만 있고 `document` DB 행이 없다. 부트스트랩 또는 문서 업로드 API를 사용한다. |
| 팀원마다 검색 문서 수가 다름 | PDF 코퍼스가 동일하게 배포되지 않았거나 서로 다른 DB를 보고 있다. PDF 개수와 세 `.env`의 DB/URL을 비교한다. |
| 색인 중 일부 실패 | 출력의 파일명을 확인하고 같은 `--apply` 명령을 다시 실행한다. 실패 문서는 `is_loaded=FALSE`로 남는다. |
