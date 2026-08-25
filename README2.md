# Django 이관 및 MySQL 통합 문서

이 문서는 기존 WEB 계층을 Django 5.2로 이관하고, Django WEB·LLM·RAG가 같은 MySQL `rag_chatbot` 데이터베이스를 사용하도록 정리한 현재 기준 문서입니다.

전체 팀 실행 절차는 [RAG/SETUP.md](RAG/SETUP.md)를 함께 참고합니다.

## 현재 아키텍처

```text
Browser
  ↓
Django WEB :8000
  ├─ MySQL: user, user_login_history, chatroom, chat, chat_source, document
  └─ HTTP → LLM :8002
                 └─ HTTP → RAG :8001
                              ├─ MySQL: document 메타데이터 조회·갱신
                              ├─ RAG/res/pdf: 원본 PDF
                              └─ RAG/vector_store: PC별 FAISS 인덱스
```

RAG와 LLM은 FastAPI 서비스로 유지됩니다. Django로 이관한 범위는 WEB 화면, 인증, 채팅 저장, 관리자 화면, 그리고 공용 `document` 테이블의 마이그레이션 소유권입니다.

## 이관 결과

| 영역 | 현재 상태 |
| --- | --- |
| 웹 프레임워크 | Django `>=5.2,<5.3` |
| ORM | Django ORM |
| 템플릿 | Django Templates |
| 인증 | 커스텀 `users.User`, bcrypt 호환 비밀번호 처리 |
| DB | 팀 통합 환경은 MySQL 8 `rag_chatbot` |
| 문서 메타데이터 | `documents` Django 앱의 `document` 테이블 |
| RAG 인덱스 | FastAPI RAG가 관리하는 로컬 FAISS `vector_store` |

`web/app/`의 예전 FastAPI 구현은 현재 Django 서버의 런타임 경로가 아닙니다. 표준 실행 진입점은 `web/manage.py`입니다.

## Django 프로젝트 구조

```text
web/
├── config/                    # settings.py, urls.py, WSGI/ASGI
├── users/                     # User, 로그인·회원가입, 사용자·통계 관리자 화면
├── chat/                      # Chatroom, Chat, ChatSource, LLM 호출
├── documents/                 # document 모델과 마이그레이션
├── templates/                 # Django 템플릿
├── static/                    # CSS, JavaScript, 이미지
├── manage.py                  # Django 관리 명령
└── run.py                     # 개발 서버 보조 진입점
```

## 공용 MySQL 설정

세 서비스가 같은 DB를 바라봐야 합니다.

| 위치 | 필수 관계 |
| --- | --- |
| `web/.env` | `DATABASE_URL`의 DB명 = `rag_chatbot` |
| `RAG/.env` | `RAG_DB_NAME=rag_chatbot`, 나머지 `RAG_DB_*`도 같은 MySQL 연결 정보 |
| `LLM/.env` | `RAG_BASE_URL=http://127.0.0.1:8001` |

`DATABASE_URL` 예시 형식은 다음과 같습니다. 실제 비밀번호는 저장소에 기록하지 않습니다.

```dotenv
DATABASE_URL=mysql+pymysql://<user>:<password>@127.0.0.1:3306/rag_chatbot?charset=utf8mb4
```

`web/config/settings.py`는 이 URL을 안전하게 파싱해 MySQL에 연결합니다. URL이 비어 있으면 개발용 SQLite 폴백이 가능하지만, RAG 통합·팀 테스트의 기준은 MySQL입니다.

## 첫 실행 절차

### 1. 빈 MySQL DB와 환경변수 준비

MySQL에 `rag_chatbot` DB가 없을 때만 생성합니다.

```sql
CREATE DATABASE rag_chatbot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

각 서비스에서 `.env.example`을 `.env`로 복사하고 실제 연결 정보·API 키를 채웁니다.

### 2. Django 마이그레이션

```powershell
cd D:\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py migrate --noinput
```

체크인된 마이그레이션이 스키마의 기준입니다. 일반 팀원은 `makemigrations`를 실행하지 않습니다. 모델을 변경하는 개발자만 새 마이그레이션을 만들고 함께 커밋합니다.

### 3. PDF 등록과 FAISS 인덱스 생성

RAG 서버를 끈 상태에서 실행합니다.

```powershell
cd D:\SKN32-4th-2Team\RAG
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply
```

이 도구는 `res/pdf`의 PDF를 `document`에 등록하고 `vector_store/<doc_id>`를 생성합니다. 기본 실행은 쓰기 없는 미리보기이며, `--apply`에서만 실제 등록·색인이 수행됩니다.

다음 레거시 스크립트는 현재 초기화에 사용하지 않습니다.

- `RAG/sql/rag_document.sql`: `TRUNCATE TABLE document`를 포함하고 일부 고정 문서만 등록
- 예전 전체 스키마 SQL: Django가 만든 사용자·채팅 테이블과 충돌 가능

### 4. 서버 실행

RAG → LLM → Django 순으로 실행합니다. RAG의 `Application startup complete`와 `/health`의 `models_ready: true`가 나온 뒤 LLM을 시작해야 첫 질문이 모델 적재를 떠안지 않습니다.

```powershell
# RAG
cd D:\SKN32-4th-2Team\RAG
.\.venv\Scripts\python.exe app.py

# LLM
cd D:\SKN32-4th-2Team\LLM
.\.venv\Scripts\python.exe -m app.main

# Django WEB
cd D:\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

첫 초기화가 끝난 뒤에는 MySQL과 세 서버만 다시 켜면 됩니다. 단, 새 PC·새 DB·삭제된 `vector_store`·새 PDF·파이프라인 설정 변경 시에는 RAG 부트스트랩을 다시 실행합니다.

## URL 구조

| 영역 | 대표 경로 |
| --- | --- |
| 시작·로그인 | `GET /`, `GET /login/`, `POST /login/auth/login` |
| 회원가입 | `GET /login/auth/check-user-id`, `POST /login/auth/signup` |
| 채팅 | `GET /chat/`, `GET /chat/<chatroom_id>` |
| 채팅 API | `GET /chat/api/rooms`, `POST /chat/api/rooms/create`, `POST /chat/api/rooms/<id>/messages/send` |
| 관리자 사용자 | `GET /admin/users/` |
| 관리자 문서 | `GET /admin/documents/` |
| 관리자 통계 | `GET /admin/stats/`, `GET /admin/stats/api/summary` |

RAG 문서 관리 페이지는 `DOC_API_BASE_URL`을 통해 RAG FastAPI에 직접 연결합니다. PDF 한 건 업로드는 자동 색인되지만, 새 환경 전체 코퍼스는 부트스트랩 도구로 등록하는 것이 기준입니다.

## 확인 체크리스트

- [ ] Django `manage.py migrate --noinput` 성공
- [ ] PDF 부트스트랩 결과에서 실패 문서 0건
- [ ] RAG `/health`, `/api/documents`, `/api/search` 정상
- [ ] LLM `/health` 정상
- [ ] Django 로그인·채팅·근거 문서 표시 정상
- [ ] 관리자 문서·통계 화면 정상

## 참고 문서

- [루트 실행 안내](README.md)
- [Django WEB README](web/README.md)
- [RAG README](RAG/README.md)
- [LLM README](LLM/README.md)
- [팀 공용 실행 가이드](RAG/SETUP.md)
