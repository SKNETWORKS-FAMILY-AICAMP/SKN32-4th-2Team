# Smart HR WEB

사용자 인증, 채팅 기록, 관리자 화면을 제공하는 Django 5.2 웹 서비스입니다. 답변 생성은 LLM 서비스가, PDF 등록·검색은 RAG 서비스가 담당합니다.

```text
Browser → Django WEB (8000) → LLM (8002) → RAG (8001)
                 │                         ├─ MySQL document 메타데이터
                 └─ MySQL 사용자·채팅 데이터 └─ PC별 FAISS vector_store
```

새 PC·새 DB에서의 전체 실행 순서는 [전체 실행 가이드](../SETUP.md)를 기준으로 합니다. 이 문서는 Django 설정과, 이전 MySQL이 남아 있는 경우의 일회성 데이터 이관 절차를 설명합니다.

## 현재 구조

```text
web/
├── config/       # settings, URL 설정, WSGI/ASGI
├── users/        # 커스텀 User, 로그인·회원가입, 관리자·통계 화면
├── chat/         # 채팅방·메시지·근거 문서 저장과 LLM 호출
├── documents/    # RAG document 테이블의 Django 마이그레이션 소유 앱
├── legacy_import/ # 이전 MySQL을 읽기 전용으로 이관하는 일회성 도구
├── templates/    # Django 템플릿
├── static/       # CSS, JavaScript, 이미지
├── manage.py     # 표준 Django 관리 명령
└── run.py        # 개발 서버 보조 진입점
```

현재 런타임의 기준은 `manage.py`와 `config/`, `users/`, `chat/`, `documents/`입니다. `web/app/` 아래의 과거 FastAPI 코드에는 의존하지 않습니다.

## DB 역할과 환경변수

`web/.env.example`을 `web/.env`로 복사하고 실제 값만 채웁니다.

| 구분 | MySQL DB | 사용하는 곳 | 용도 |
| --- | --- | --- | --- |
| 새 운영 대상 | `rag_chatbot_v4` | Django `DATABASE_URL`, RAG `RAG_DB_*` | 현재 서비스가 읽고 쓰는 유일한 DB |
| 레거시 원본 | 이전 PC에 남은 **과거 DB명** (예: `rag_chatbot`) | `import_legacy_data` 실행 중 `LEGACY_DATABASE_URL`만 | 일회성 읽기 원본. Django/RAG 서버는 사용하지 않음 |

`rag_chatbot_v4`는 팀 표준 대상 DB명입니다. Django의 `DATABASE_URL`과 RAG의 `RAG_DB_HOST`·`RAG_DB_PORT`·`RAG_DB_NAME`은 반드시 같은 **새 운영 대상**을 가리켜야 합니다. 이 문서에서 보이는 `rag_chatbot`은 과거 원본의 예시일 뿐이며, 새 운영 대상 `DATABASE_URL`에 사용하지 않습니다. 레거시 DB는 같은 MySQL 서버에 있어도 되지만, 대상과 DB/schema가 달라야 합니다.

| 변수 | 용도 |
| --- | --- |
| `DATABASE_URL` | Django가 쓰는 새 운영 MySQL URL. 표준 URL의 DB/schema는 `rag_chatbot_v4`이며, 레거시 `rag_chatbot`을 대상으로 쓰지 않음 |
| `LEGACY_DATABASE_URL` | 선택 사항. `import_legacy_data`에서만 쓰는 레거시 원본 읽기 전용 URL. 대상과 같은 host·port·DB/schema를 가리키면 안 됨 |
| `SESSION_SECRET_KEY` | Django 세션 서명 키 |
| `SESSION_MAX_AGE_SECONDS` | 로그인 세션 유효 시간(기본 3시간) |
| `CHAT_API_BASE_URL` | LLM 서비스 주소, 기본 통합값 `http://127.0.0.1:8002` |
| `CHAT_API_TIMEOUT_SECONDS` | LLM 응답 대기 시간(초). RAG 45초 + LLM 15초와 통신 여유를 고려한 기본값은 `70` |
| `DOC_API_BASE_URL` | RAG 문서 API 주소, 기본 통합값 `http://127.0.0.1:8001` |

팀 통합 환경에서는 MySQL을 사용합니다. `DATABASE_URL`이 비어 있으면 Django 설정은 로컬 SQLite로 폴백할 수 있지만, RAG와 함께 쓰는 표준 환경에서는 사용하지 않습니다.

## 실행 경로 선택

| 상황 | `web/.env` | 실행 순서 |
| --- | --- | --- |
| 이전 DB가 없는 팀원 | `DATABASE_URL`만 새 `rag_chatbot_v4`로 설정 | 새 DB 생성 → `migrate` → PDF 부트스트랩 |
| 이전 DB가 남아 있는 팀원 | 위 설정 + 읽기 전용 `LEGACY_DATABASE_URL` | 새 DB 생성 → `migrate` → 사용자·채팅 이관 dry-run/`--apply` → 새 PDF 부트스트랩 |

이전 DB가 없는 팀원은 아래 첫 실행 절차만 따르면 됩니다. `LEGACY_DATABASE_URL`을 설정하지 않고 `import_legacy_data`도 실행하지 않습니다. 이전 DB를 보유한 팀원도 먼저 같은 새 대상 DB를 만들고 `migrate`를 완료한 뒤에만 별도 이관 단계를 실행합니다.

## 첫 실행

가상환경과 의존성을 준비합니다.

```powershell
cd D:\Dev_Tools\SKN32-4th-2Team\web
py -3.11 -m venv .venv-django
.\.venv-django\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

MySQL의 빈 `rag_chatbot_v4` DB와 `.env` 설정이 준비된 뒤 마이그레이션을 실행합니다.

```powershell
.\.venv-django\Scripts\python.exe manage.py migrate --noinput
```

마이그레이션은 `user`, `user_login_history`, `chatroom`, `chat`, `chat_source`, `document`를 포함한 공용 테이블을 만듭니다. 팀원이 보통 `makemigrations`를 실행할 필요는 없으며, 모델을 실제로 변경한 개발자만 새 마이그레이션을 생성합니다.

## 기존 DB 데이터 이관 (레거시 DB 보유자만)

다른 팀원 PC에 남아 있는 이전 MySQL은 **원본**으로만 연결합니다. `web/.env`의 `DATABASE_URL`은 새 운영 DB `rag_chatbot_v4`로 유지하고, `LEGACY_DATABASE_URL`에만 원본의 읽기 전용 계정을 설정합니다. 두 URL이 같은 host·port·DB/schema를 가리키면 설정 단계와 명령 실행 단계에서 모두 중단됩니다.

`legacy_import`의 모델은 `managed=False`이며 쓰기를 막지만, 이것만으로 MySQL 권한을 제한하는 것은 아닙니다. 레거시 URL에는 반드시 `SELECT` 권한만 가진 계정을 사용하세요. 레거시 DB에는 `migrate`, `makemigrations`, `--fake-initial`을 실행하지 않습니다.

먼저 새 운영 DB에 위 마이그레이션을 완료한 뒤, 아래처럼 결과만 확인하는 기본 실행을 합니다.

```powershell
cd D:\Dev_Tools\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py import_legacy_data
```

출력의 원본·생성·건너뜀 건수를 검토한 뒤에만 실제 이관을 실행합니다.

```powershell
.\.venv-django\Scripts\python.exe manage.py import_legacy_data --apply
```

기본 명령은 dry-run이며 쓰기를 하지 않습니다. `--apply`만 새 운영 DB에 하나의 트랜잭션으로 기록합니다. 이관 도구는 **`user`, `user_login_history`, `chatroom`, `chat`, `chat_source`만** 가져오며, PK·기록 시각·기존 bcrypt 비밀번호 해시를 보존합니다. `chat_source`의 `file_name`·`page`는 과거 채팅에 표시할 근거 스냅샷으로 보존됩니다. 레거시 RAG `document`는 전혀 읽거나 쓰지 않습니다. 따라서 이관된 `chat_source.doc_id`는 새 RAG 문서와 일치하지 않을 수 있지만, 파일명·페이지 근거 표시는 유지됩니다.

`--apply`는 위 다섯 사용자·채팅 대상 테이블이 비어 있을 때만 기본적으로 실행됩니다. RAG를 완전히 새로 시작시키기 위해 대상의 `document`도 비어 있어야 합니다. 회원가입, 채팅, 문서 부트스트랩 등으로 대상에 데이터가 생기기 전에 이관하세요. 검토된 중단 이관을 재개하는 경우에만 `--allow-nonempty-target`을 사용할 수 있으며, 그때도 기존 PK는 덮어쓰지 않고 건너뜁니다. 이 옵션으로도 `document`가 비어 있지 않으면 이관은 중단됩니다. 이관 뒤에도 Django와 RAG는 새 `rag_chatbot_v4`만 사용합니다. `LEGACY_DATABASE_URL`은 제거하거나 비워 두는 것을 권장합니다.

이전 DB가 여러 PC에 남아 있으면 먼저 각 후보에 대해 dry-run 결과(테이블별 건수와 최신 시각)를 비교해 **정본 원본 한 개**를 정합니다. 서로 다른 PC의 DB를 같은 대상에 차례로 이관해 자동 병합하는 기능은 제공하지 않습니다. 같은 PK의 사용자·채팅이 충돌하거나 어느 쪽이 최신인지 판단할 수 없기 때문입니다.

`Table 'user' already exists` 오류가 나오면 레거시 DB를 `DATABASE_URL`로 설정한 채 `migrate`를 실행했는지 먼저 확인합니다. `--fake-initial`로 넘기지 말고, `DATABASE_URL`을 비어 있는 새 `rag_chatbot_v4`로 되돌린 뒤 마이그레이션부터 다시 확인하세요.

## 이관 후 새 RAG 코퍼스 만들기

이관 도구는 PDF, `document` 메타데이터, 이전 PC의 `RAG/vector_store`를 모두 제외합니다. `chat_source`만 과거 화면의 파일명·페이지 스냅샷으로 이관하며, 이것은 새 RAG 문서 등록이나 PDF 파일명 매칭에는 사용되지 않습니다. 즉 이전 PDF와 현재 PDF의 같은 파일명은 이관 과정에서 비교하거나 연결하지 않습니다. RAG 검색 코퍼스는 빈 `document` 테이블과 새 인덱스에서 시작합니다.

현재 서비스에 쓸 **정본 PDF만** 현재 PC의 `RAG/res/pdf`(또는 RAG 부트스트랩의 `--pdf-dir`)에 준비합니다. 부트스트랩은 지정한 현재 폴더만 스캔하며, 이전 프로젝트 폴더를 자동으로 읽지 않습니다. 같은 파일명이라도 PDF 내용이 다르면 RAG 부트스트랩은 내용 해시를 비교하지 않으므로, 현재 폴더에는 의도한 PDF 한 벌만 두세요.

`vector_store/<doc_id>`는 PC별 로컬 파일입니다. 완전히 새 RAG를 시작하려면 기존 `RAG/vector_store`를 활성 경로 밖으로 백업·이동하거나, 백업 확인 후 비워 두세요. 이전 인덱스를 복사해 재사용하지 마세요. 기존 유효 인덱스가 남아 있으면 기본 `skip` 모드가 재색인하지 않고 상태만 복구할 수 있습니다.

```powershell
cd ..\RAG
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply
```

기존 인덱스가 남아 있지만 현재 PDF 전체를 다시 색인해야 할 때는, 먼저 아래 dry-run 결과를 확인한 뒤 `--apply`를 실행합니다. `--mode overwrite`는 현재 PDF에 해당하는 인덱스만 교체하므로, 완전한 새 시작에는 기존 `vector_store`를 먼저 활성 경로 밖으로 옮기는 편이 안전합니다.

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --mode overwrite
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply --mode overwrite
```

`RAG/sql/rag_document.sql`은 `TRUNCATE`가 포함된 과거 시드 파일이므로 실행하지 않습니다.

## 서버 실행

RAG와 LLM이 먼저 실행된 뒤 Django를 실행합니다. RAG는 `Application startup complete`와 `/health`의 `models_ready: true`가 나온 뒤에 LLM을 시작해야 첫 채팅이 모델 로딩으로 시간 초과되지 않습니다.

```powershell
cd D:\Dev_Tools\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

브라우저에서 `http://127.0.0.1:8000`으로 접속합니다. 일반적인 재실행에서는 `migrate`와 PDF 부트스트랩을 다시 할 필요 없이 MySQL·RAG·LLM·Django 서버만 차례로 켭니다.

## 주요 경로

| 영역 | 경로 |
| --- | --- |
| 시작 | `GET /` |
| 로그인 화면 | `GET /login/` |
| 로그인·회원가입·로그아웃 | `POST /login/auth/login`, `POST /login/auth/signup`, `POST /login/auth/logout` |
| 아이디 중복 확인 | `GET /login/auth/check-user-id` |
| 채팅 | `GET /chat/`, `GET /chat/<chatroom_id>` |
| 채팅 API | `GET /chat/api/rooms`, `POST /chat/api/rooms/create`, `POST /chat/api/rooms/<id>/messages/send` |
| 관리자 사용자 | `GET /admin/users/` |
| 관리자 문서 | `GET /admin/documents/` |
| 관리자 통계 | `GET /admin/stats/`, `GET /admin/stats/api/summary` |

문서 관리 화면은 `DOC_API_BASE_URL`을 사용해 RAG API에 직접 연결합니다. PDF 한 건 업로드는 RAG가 자동으로 DB 등록과 색인을 수행하지만, 새 환경의 전체 코퍼스는 RAG 부트스트랩 도구로 준비하는 것이 기준입니다.

## 확인 방법

1. RAG `http://127.0.0.1:8001/health`와 LLM `http://127.0.0.1:8002/health`를 확인합니다.
2. 레거시 이관을 했다면 `import_legacy_data` dry-run/`--apply`의 테이블별 건수와 RAG 부트스트랩의 등록·재사용·색인 결과를 보관합니다.
3. Django에 회원가입·로그인합니다.
4. 일반 사용자로 채팅을 보내 답변과 근거 문서가 저장되는지 확인합니다.
5. 관리자 계정으로 문서·통계 화면을 확인합니다.

## 관련 문서

- [전체 실행 가이드](../SETUP.md)
- [RAG 서비스](../RAG/README.md)
- [LLM 서비스](../LLM/README.md)
- [Django 이관·MySQL 통합 문서](../README2.md)
