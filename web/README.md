# Smart HR WEB

사용자 인증, 채팅 기록, 관리자 화면을 제공하는 Django 5.2 웹 서비스입니다. 답변 생성은 LLM 서비스가, PDF 등록·검색은 RAG 서비스가 담당합니다.

```text
Browser → Django WEB (8000) → LLM (8002) → RAG (8001)
                 │                         ├─ MySQL document 메타데이터
                 └─ MySQL 사용자·채팅 데이터 └─ PC별 FAISS vector_store
```

새 PC·새 DB에서의 전체 실행 순서는 [../RAG/SETUP.md](../RAG/SETUP.md)를 기준으로 합니다.

## 현재 구조

```text
web/
├── config/       # settings, URL 설정, WSGI/ASGI
├── users/        # 커스텀 User, 로그인·회원가입, 관리자·통계 화면
├── chat/         # 채팅방·메시지·근거 문서 저장과 LLM 호출
├── documents/    # RAG document 테이블의 Django 마이그레이션 소유 앱
├── templates/    # Django 템플릿
├── static/       # CSS, JavaScript, 이미지
├── manage.py     # 표준 Django 관리 명령
└── run.py        # 개발 서버 보조 진입점
```

현재 런타임의 기준은 `manage.py`와 `config/`, `users/`, `chat/`, `documents/`입니다. `web/app/` 아래의 과거 FastAPI 코드에는 의존하지 않습니다.

## 환경변수

`web/.env.example`을 `web/.env`로 복사하고 실제 값만 채웁니다.

| 변수 | 용도 |
| --- | --- |
| `DATABASE_URL` | 공용 MySQL URL. DB명은 RAG의 `RAG_DB_NAME`과 같은 `rag_chatbot`이어야 함 |
| `SESSION_SECRET_KEY` | Django 세션 서명 키 |
| `SESSION_MAX_AGE_SECONDS` | 로그인 세션 유효 시간(기본 3시간) |
| `CHAT_API_BASE_URL` | LLM 서비스 주소, 기본 통합값 `http://127.0.0.1:8002` |
| `CHAT_API_TIMEOUT_SECONDS` | LLM 응답 대기 시간(초). RAG 45초 + LLM 15초와 통신 여유를 고려한 기본값은 `70` |
| `DOC_API_BASE_URL` | RAG 문서 API 주소, 기본 통합값 `http://127.0.0.1:8001` |

팀 통합 환경에서는 MySQL을 사용합니다. `DATABASE_URL`이 비어 있으면 Django 설정은 로컬 SQLite로 폴백할 수 있지만, RAG와 함께 쓰는 표준 환경에서는 사용하지 않습니다.

## 첫 실행

가상환경과 의존성을 준비합니다.

```powershell
cd D:\SKN32-4th-2Team\web
py -3.11 -m venv .venv-django
.\.venv-django\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

MySQL의 빈 `rag_chatbot` DB와 `.env` 설정이 준비된 뒤 마이그레이션을 실행합니다.

```powershell
.\.venv-django\Scripts\python.exe manage.py migrate --noinput
```

마이그레이션은 `user`, `chatroom`, `chat`, `chat_source`, `document`를 포함한 공용 테이블을 만듭니다. 팀원이 보통 `makemigrations`를 실행할 필요는 없으며, 모델을 실제로 변경한 개발자만 새 마이그레이션을 생성합니다.

그 다음 RAG 폴더에서 PDF 부트스트랩을 완료해야 합니다.

```powershell
cd ..\RAG
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply
```

`RAG/sql/rag_document.sql`은 `TRUNCATE`가 포함된 과거 시드 파일이므로 실행하지 않습니다.

## 서버 실행

RAG와 LLM이 먼저 실행된 뒤 Django를 실행합니다. RAG는 `Application startup complete`와 `/health`의 `models_ready: true`가 나온 뒤에 LLM을 시작해야 첫 채팅이 모델 로딩으로 시간 초과되지 않습니다.

```powershell
cd D:\SKN32-4th-2Team\web
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
2. Django에 회원가입·로그인합니다.
3. 일반 사용자로 채팅을 보내 답변과 근거 문서가 저장되는지 확인합니다.
4. 관리자 계정으로 문서·통계 화면을 확인합니다.

## 관련 문서

- [전체 실행 가이드](../RAG/SETUP.md)
- [RAG 서비스](../RAG/README.md)
- [LLM 서비스](../LLM/README.md)
- [Django 이관·MySQL 통합 문서](../README2.md)
