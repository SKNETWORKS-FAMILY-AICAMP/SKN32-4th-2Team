# Smart HR — 사내 RAG 챗봇

사내 인사/총무 문의에 답변하는 RAG 기반 챗봇 서비스. FastAPI 백엔드 + 서버사이드 렌더링(Jinja2) 웹 화면으로 구성되며, 실제 답변 생성(LLM)과 문서 적재(RAG 파이프라인)는 별도로 떠 있는 외부 API 서버와 연동한다.

## 목차

- [기술 스택](#기술-스택)
- [디렉토리 구조](#디렉토리-구조)
- [화면 / 기능](#화면--기능)
- [API 라우트 정리](#api-라우트-정리)
- [외부 연동](#외부-연동)
- [세션 정책](#세션-정책)
- [초기 세팅](#초기-세팅)
- [환경변수](#환경변수)
- [DB](#db)

---

## 기술 스택

- **백엔드**: FastAPI, SQLAlchemy(ORM), MySQL 8.0(운영) / SQLite(로컬 개발 대체 가능)
- **세션**: Starlette `SessionMiddleware` (서명 쿠키), 서버사이드 만료 검증
- **화면**: Jinja2 서버사이드 렌더링 + 순수 JS(프레임워크 없음), 커스텀 CSS
- **외부 연동**: Chat API 서버(LLM 답변 생성), 문서 API 서버(RAG 문서 업로드/적재) — 둘 다 이 리포 밖에 별도로 존재

## 디렉토리 구조

```
app/
  main.py                       # FastAPI 앱 생성, 미들웨어, 라우터 등록, lifespan(워밍업)
  core/
    security.py                 # 비밀번호 해싱, 세션 read/write, require_login/require_admin 등
    database.py                 # SQLAlchemy engine/session, Base, get_db, DB 워밍업
  models/
    user.py                     # User, UserLoginHistory
    chat.py                     # Chatroom, Chat, ChatSource
  services/
    user_service.py             # 유저 CRUD, 로그인 이력 기록
    chat_service.py             # 메시지 저장/조회, Chat API 호출, 근거문서 저장
    llm_client.py               # Chat API 서버와 통신하는 httpx 클라이언트(싱글턴)
  routers/
    pages.py                    # "/" 진입점 (로그인 여부/역할에 따라 리다이렉트)
    auth.py                     # 로그인/회원가입/로그아웃/아이디 중복확인
    admin/
      user_router.py            # 사용자 관리 (목록/추가/수정/삭제)
      document_router.py        # RAG 문서관리 페이지 셸
      stats_router.py           # 통계 페이지 셸
    chat/
      chat_router.py            # 채팅방/메시지 API + 채팅 화면

templates/
  login.html                    # 로그인 화면 (회원가입 모달 포함)
  layout/app_base.html          # 로그인 후 공통 레이아웃 (헤더+사이드바)
  partials/                     # header, sidebar, user_modal(회원가입/추가/수정 공용)
  admin/                        # users.html, documents.html, stats.html
  chat/                         # chat.html (채팅 UI, 별도 작업 중)

static/
  css/                          # style.css(공통), rag.css(문서관리 전용)
  js/                           # session_guard.js, user_modal.js, users.js, rag.js
  img/                          # 로고 등 (일부 자산 미포함, 아래 TODO 참고)
```

## 화면 / 기능

| 화면 | 대상 | 설명 |
|---|---|---|
| 로그인 (`/login`) | 전체 | 로그인 폼 + 회원가입 모달(아이디 중복확인 포함) |
| 채팅 (`/chat`, `/chat/{chatroom_id}`) | 일반 유저 | 대화방 목록, 메시지 전송, 답변 하단 근거 문서 표시 |
| 사용자 관리 (`/admin/users`) | 관리자 | 목록 검색/페이지네이션, 추가/수정(권한·비활성 포함)/삭제(소프트 삭제) |
| RAG 문서관리 (`/admin/documents`) | 관리자 | 문서 업로드(업로드 즉시 자동 적재), 전체 적재(미적재 문서 일괄), PDF 미리보기 — 브라우저가 문서 API 서버를 **직접** 호출 |
| 통계 (`/admin/stats`) | 관리자 | 요약 지표, 카테고리별 문의 비율, 일자별 추이, FAQ TOP10 |

관리자는 챗봇 메뉴가 보이지 않으며(사내 문의 응대는 일반 유저 전용), 로그인하면 바로 통계 화면으로 이동한다.

## API 라우트 정리

**인증 (`app/routers/auth.py`)**

| Method | Path | 설명 |
|---|---|---|
| GET | `/login` | 로그인 페이지 |
| POST | `/auth/login` | 로그인 처리 |
| POST | `/auth/signup` | 회원가입 (fetch, 모달 내 비동기 처리) |
| GET | `/auth/check-user-id` | 아이디 중복확인 |
| POST | `/auth/logout` | 로그아웃 |

**진입점 (`app/routers/pages.py`)**

| Method | Path | 설명 |
|---|---|---|
| GET | `/` | 로그인 여부/역할에 따라 `/login`, `/chat`, `/admin/stats`로 리다이렉트 |

**채팅 (`app/routers/chat/chat_router.py`, prefix `/chat`)**

| Method | Path | 설명 |
|---|---|---|
| GET | `/chat` | 채팅 화면 (대화방 미선택 상태) |
| GET | `/chat/{chatroom_id}` | 채팅 화면 (특정 대화방) |
| GET | `/chat/api/rooms` | 내 대화방 목록 |
| POST | `/chat/api/rooms` | 대화방 생성 |
| GET | `/chat/api/rooms/{chatroom_id}/messages` | 대화 내역 조회 (근거 문서 포함) |
| POST | `/chat/api/rooms/{chatroom_id}/messages` | 메시지 전송 (Chat API 호출 + 저장) |
| DELETE | `/chat/api/rooms/{chatroom_id}` | 대화방 삭제 (소프트 삭제) |

**관리자 - 사용자관리 (`app/routers/admin/user_router.py`, prefix `/admin/users`)**

| Method | Path | 설명 |
|---|---|---|
| GET | `/admin/users` | 사용자 관리 페이지 셸 |
| GET | `/admin/users/api/list` | 목록 조회 (검색/페이지네이션) |
| POST | `/admin/users/api/create` | 사용자 추가 |
| PATCH | `/admin/users/api/{user_id}` | 사용자 수정 (이름/부서/비밀번호/권한/비활성여부) |
| DELETE | `/admin/users/api/{user_id}` | 사용자 삭제 (소프트 삭제, 본인 계정은 삭제 불가) |

**관리자 - 문서관리 / 통계**

| Method | Path | 설명 |
|---|---|---|
| GET | `/admin/documents` | 문서관리 페이지 셸 (`DOC_API_BASE_URL`을 화면에 주입) |
| GET | `/admin/stats` | 통계 페이지 셸 |

모든 `/admin/*` 라우트는 관리자 권한(`require_admin`/`require_admin_api`)이 필요하다.

## 외부 연동

이 프로젝트는 **두 개의 외부 API 서버**와 통신한다. 둘 다 이 리포 밖에서 별도로 운영된다.

1. **Chat API 서버** (`CHAT_API_BASE_URL`) — `app/services/llm_client.py`가 서버 대 서버로 호출한다.
   - `POST /v1/chat` — 답변 생성 (질문 + 최근 대화 3쌍 → 답변/주제/근거문서/`rag_degraded`)
   - `POST /v1/chatroom-name` — 대화방 첫 메시지일 때 제목 생성 (답변 생성과 병렬 호출)
   - `GET /health` — 상태 확인 (현재 어디서도 호출 안 함, 준비만 해둠)
   - 에러는 `{"error_code": "...", "message": "..."}` 형태로 통일되어 있으며, `LLM_TIMEOUT`/`LLM_UNAVAILABLE`/`PROVIDER_NOT_CONFIGURED`/`INVALID_REQUEST`/`INTERNAL_ERROR` 5종.
   - 에러가 나도 사용자 질문은 저장되고(topic="에러"), llm 자리에 에러 안내 메시지가 저장된다.

2. **문서 API 서버** (`DOC_API_BASE_URL`) — `/admin/documents` 페이지의 `rag.js`가 **브라우저에서 직접** 호출한다 (우리 백엔드를 거치지 않음). 우리 백엔드는 페이지 진입 시 권한 검사와 `DOC_API_BASE_URL` 값을 화면에 심어주는 역할만 한다.

## 세션 정책

- 로그인 성공 시 서명된 세션 쿠키에 `user_id`, `name`, `is_admin`, `login_at`을 저장한다.
- **실제 로그인 유효시간**은 `SESSION_MAX_AGE_SECONDS`(기본 3시간)이며, `core/security.py`가 `login_at` 기준으로 매 요청마다 검증한다.
- **쿠키 자체의 수명**은 이보다 훨씬 길게(유효시간 + 7일) 잡혀 있다 — 그래야 세션이 실제로 만료된 뒤에도 브라우저가 쿠키를 계속 보내서, "세션이 있다가 만료됨"과 "애초에 로그인한 적 없음"을 서버가 구분할 수 있다 (`_had_session_cookie`).
- 페이지 이동 중 만료를 감지하면 `/login?expired=1`로 보내 안내 문구를 띄우고, API(fetch) 호출 중 만료를 감지하면 `static/js/session_guard.js`가 전역으로 알림을 띄우고 로그인 화면으로 보낸다.
- 로컬에서 만료 동작을 테스트하려면 `.env`에 `SESSION_MAX_AGE_SECONDS=10`처럼 짧게 넣었다가 테스트 후 지우면 된다.

## 초기 세팅

```bash
# 1. 파이썬 의존성 설치
pip install -r requirements.txt

# 2. .env 준비 (.env.example 참고해서 값 채우기)
cp .env.example .env

# 3. 서버 실행
python run.py
# 또는
uvicorn app.main:app --reload
```

브라우저에서 `http://localhost:8000` 접속 (로그인 안 된 상태면 자동으로 `/login`으로 이동).

## 환경변수

| 변수 | 설명 | 기본값 |
|---|---|---|
| `DATABASE_URL` | MySQL 연결 문자열. 예: `mysql+pymysql://user:pw@host:3306/rag_chatbot?charset=utf8mb4` | 미설정 시 서버 기동 실패(필수 자원이라 fail-fast) |
| `SESSION_SECRET_KEY` | 세션 쿠키 서명 키 (운영 배포 시 반드시 변경) | `dev-secret-change-me` |
| `SESSION_MAX_AGE_SECONDS` | 세션(로그인) 유효 시간(초). 로컬 테스트 시 짧게 줄여서 만료 동작 확인 가능 | `10800` (3시간) |
| `CHAT_API_BASE_URL` | Chat API 서버 주소 | 미설정 시 채팅 요청이 `PROVIDER_NOT_CONFIGURED`로 즉시 실패 (서버 자체는 정상 기동) |
| `CHAT_API_TIMEOUT_SECONDS` | Chat API 응답 대기 타임아웃(초). 서버 쪽 5초 타임아웃보다 넉넉해야 504가 제대로 전달됨 | `15` |
| `DOC_API_BASE_URL` | 문서 API 서버 주소 (브라우저가 직접 호출) | 미설정 시 프론트가 기존 상대경로(`/api`)로 폴백 |

## DB

주요 테이블: `user`, `user_login_history`, `chatroom`, `chat`, `chat_source`, `document`. 스키마 DDL/ERD/테이블 명세서는 이 리포와 별도로 관리 중이며, `user` 테이블에 컬럼을 추가할 때는 별도 마이그레이션 SQL을 함께 공유했다 (계정 삭제/수정일자 관련).

앱 시작 시 DB 연결을 한 번 확인(warm-up)하며, 연결이 안 되면 서버 기동 자체가 실패한다 (첫 요청에서야 실패를 알게 되는 것보다 낫다는 판단).
