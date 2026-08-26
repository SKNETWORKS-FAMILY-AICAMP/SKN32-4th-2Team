# Django 이관 및 MySQL 통합 문서

이 문서는 기존 WEB 계층을 Django 5.2로 이관하고, Django WEB·LLM·RAG가 같은 새 MySQL `rag_chatbot_v4` 데이터베이스를 사용하도록 정리한 현재 기준 문서입니다.

전체 팀 실행 절차는 [SETUP.md](SETUP.md)를 함께 참고합니다.

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
| DB | 팀 통합 환경은 MySQL 8 `rag_chatbot_v4` |
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
├── legacy_import/             # 읽기 전용 레거시 모델과 일회성 이관 명령
├── templates/                 # Django 템플릿
├── static/                    # CSS, JavaScript, 이미지
├── manage.py                  # Django 관리 명령
└── run.py                     # 개발 서버 보조 진입점
```

## 공용 MySQL 설정

세 서비스가 같은 DB를 바라봐야 합니다.

| 위치 | 필수 관계 |
| --- | --- |
| `web/.env` | `DATABASE_URL`의 DB명 = `rag_chatbot_v4` |
| `RAG/.env` | `RAG_DB_NAME=rag_chatbot_v4`, 나머지 `RAG_DB_*`도 같은 MySQL 연결 정보 |
| `LLM/.env` | `RAG_BASE_URL=http://127.0.0.1:8001` |

`DATABASE_URL` 예시 형식은 다음과 같습니다. 실제 비밀번호는 저장소에 기록하지 않습니다.

```dotenv
DATABASE_URL=mysql+pymysql://<user>:<password>@127.0.0.1:3306/rag_chatbot_v4?charset=utf8mb4
```

`web/config/settings.py`는 이 URL을 안전하게 파싱해 MySQL에 연결합니다. URL이 비어 있으면 개발용 SQLite 폴백이 가능하지만, RAG 통합·팀 테스트의 기준은 MySQL입니다.

이전 DB가 남아 있는 PC에서만 `web/.env`에 선택 사항 `LEGACY_DATABASE_URL`을 추가합니다. 이 URL은 `import_legacy_data`의 읽기 전용 원본이며, RAG나 일반 Django 런타임은 사용하지 않습니다. `DATABASE_URL`과 `LEGACY_DATABASE_URL`은 같은 물리 DB(host, port, schema)를 가리키면 안 됩니다. DB 이름만으로 판단하지 말고 실제 연결 대상을 비교하세요. 새 운영 DB 이름을 `rag_chatbot_v4`로 고정해 혼동을 줄입니다.

이전 DB가 없는 팀원은 `DATABASE_URL`과 `RAG_DB_NAME`만 새 DB로 설정한 뒤 `migrate`와 PDF 부트스트랩을 실행합니다. `LEGACY_DATABASE_URL`과 `import_legacy_data`는 이전 DB를 보유한 팀원에게만 필요한 별도 단계입니다.

## 첫 실행 절차

### 1. 빈 MySQL DB와 환경변수 준비

MySQL에 `rag_chatbot_v4` DB가 없을 때만 생성합니다.

```sql
CREATE DATABASE rag_chatbot_v4 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

각 서비스에서 `.env.example`을 `.env`로 복사하고 실제 연결 정보·API 키를 채웁니다.

### 2. Django 마이그레이션

```powershell
cd D:\Dev_Tools\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py migrate --noinput
```

체크인된 마이그레이션이 스키마의 기준입니다. 일반 팀원은 `makemigrations`를 실행하지 않습니다. 모델을 변경하는 개발자만 새 마이그레이션을 만들고 함께 커밋합니다.

### 3. 기존 DB 데이터 이관 (레거시 DB 보유자만)

다른 팀원 PC에 이전 DB가 남아 있을 때만 이 단계를 수행합니다. 새 `rag_chatbot_v4` DB에 먼저 위 마이그레이션을 적용하고, 레거시 DB에는 절대 `migrate`를 실행하지 않습니다. 현재 서비스가 레거시 DB를 직접 운영하는 호환 모드는 만들지 않으며, 이관 도구 내부에서만 읽기 전용 `managed=False` 매핑을 사용합니다.

이관 범위는 `user`, `user_login_history`, `chatroom`, `chat`, `chat_source`입니다. `chat_source`는 PDF 적재 데이터가 아니라 답변 당시의 파일명·페이지를 보존하는 채팅 이력 스냅샷이므로, 이전 대화 표시를 유지하기 위해 함께 옮깁니다. RAG를 완전히 새로 시작하기 위해 `document`는 이관하지 않습니다. 따라서 과거 답변 아래의 근거 파일명·페이지 표시는 유지되지만, 그 안의 과거 `doc_id`는 새 RAG 문서와 연결하지 않습니다.

`web/.env`에서 `DATABASE_URL`은 새 운영 DB, `LEGACY_DATABASE_URL`은 원본의 읽기 전용 계정으로 설정한 뒤 기본 dry-run을 실행합니다.

```powershell
cd D:\Dev_Tools\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py import_legacy_data
```

테이블별 원본·생성·건너뜀 건수와 대상 DB를 확인하고, 맞을 때만 실제 이관을 실행합니다.

```powershell
.\.venv-django\Scripts\python.exe manage.py import_legacy_data --apply
```

기본 실행은 데이터를 쓰지 않습니다. `--apply`만 새 운영 DB에 트랜잭션으로 기록하며, 원본과 대상이 같은 물리 DB이면 이관을 거부합니다. 이관은 PDF 부트스트랩보다 먼저 수행해야 하며, 대상의 사용자·채팅 테이블과 `document`가 비어 있어야 합니다. 검토된 중단 이관을 위한 `--allow-nonempty-target`을 써도 `document`가 비어 있지 않으면 중단됩니다. 이관 후에는 `LEGACY_DATABASE_URL`을 제거하거나 비워 두고 Django·RAG 모두 `rag_chatbot_v4`만 사용합니다.

여러 팀원 PC에 레거시 DB가 있다면, 사용자·채팅 테이블별 건수와 최신 `created_at`/`updated_at`을 비교해 한 DB를 정본 원본으로 선정합니다. 이 도구는 여러 DB의 자동 병합을 하지 않습니다.

### 4. PDF 등록과 FAISS 인덱스 생성

RAG 서버를 끈 상태에서 실행합니다.

RAG는 레거시 DB와 무관하게 새 PDF 코퍼스와 새 `document` 메타데이터로 시작합니다. 현재 사용할 정본 PDF만 `RAG/res/pdf` 최상위에 준비합니다. 하위 폴더는 자동으로 스캔하지 않습니다.

기존 PC에 `RAG/vector_store`가 남아 있을 수 있으므로, 최초에는 자동으로 재사용하거나 삭제하지 말고 보존 필요성을 확인한 뒤 별도 백업 위치로 옮기거나 정리해 빈 상태로 만듭니다.

```powershell
cd D:\Dev_Tools\SKN32-4th-2Team\RAG
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply
```

이 도구는 PDF를 새 `document` 행에 등록하고 `vector_store/<doc_id>`를 생성합니다. 기본 실행은 쓰기 없는 미리보기이며, `--apply`에서만 실제 등록·색인이 수행됩니다. 기본 `skip` 모드는 유효한 기존 인덱스가 있으면 재색인하지 않고 적재 상태만 복구할 수 있으므로, 최초 구축 전에는 기존 `vector_store`를 깨끗이 분리합니다. 초기화가 끝난 뒤 청킹 규칙·청크 크기·오버랩·임베딩 모델을 변경했을 때는 `--apply --mode overwrite`를 사용합니다.

`overwrite`는 임시 인덱스를 성공적으로 만든 뒤에만 기존 인덱스를 교체합니다. DB 행과 연결되지 않은 고아 `vector_store` 폴더는 자동 삭제하지 않으므로, 물리적으로 완전히 비운 RAG 작업 공간이 필요하면 먼저 백업하거나 범위를 확인한 뒤 수동으로 정리합니다. PDF는 파일 경로와 원본 파일명으로 연결하며 파일 내용 해시는 비교하지 않으므로, 같은 이름에 다른 내용의 PDF는 현재 코퍼스에 섞지 말고 이름을 변경합니다.

다음 레거시 스크립트는 현재 초기화에 사용하지 않습니다.

- `RAG/sql/rag_document.sql`: `TRUNCATE TABLE document`를 포함하고 일부 고정 문서만 등록
- 예전 전체 스키마 SQL: Django가 만든 사용자·채팅 테이블과 충돌 가능

### 5. 서버 실행

RAG → LLM → Django 순으로 실행합니다. RAG의 `Application startup complete`와 `/health`의 `models_ready: true`가 나온 뒤 LLM을 시작해야 첫 질문이 모델 적재를 떠안지 않습니다.

```powershell
# RAG
cd D:\Dev_Tools\SKN32-4th-2Team\RAG
.\.venv\Scripts\python.exe app.py

# LLM
cd D:\Dev_Tools\SKN32-4th-2Team\LLM
.\.venv\Scripts\python.exe -m app.main

# Django WEB
cd D:\Dev_Tools\SKN32-4th-2Team\web
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
- [팀 공용 실행 가이드](SETUP.md)
