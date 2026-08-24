# Django 마이그레이션 문서

## 개요

FastAPI 기반 웹 애플리케이션을 Django 프레임워크로 마이그레이션한 문서입니다.

## 마이그레이션 범위

### 포함된 작업
- FastAPI → Django 프로젝트 구조 변환
- SQLAlchemy ORM → Django ORM 모델 변환
- Jinja2 템플릿 → Django 템플릿 문법 변환
- FastAPI 라우터 → Django Views/URLs 변환
- 인증 시스템 마이그레이션 (bcrypt 비밀번호 해싱 유지)
- 정적 파일 및 JavaScript CSRF 토큰 처리 추가
- URL 구조 중복 제거 및 정리

### 제외된 작업
- LLM/RAG 핵심 로직 (Python 모델, 프롬프트, FAISS, Embedding)
- 외부 API 서비스 (RAG, LLM 서버)

## 주요 수정 사항

### 1. 프로젝트 구조

```
web/
├── config/              # Django 설정 (settings.py, urls.py)
├── users/               # 사용자 앱 (인증, 관리자)
│   ├── models.py        # User, UserLoginHistory 모델
│   ├── views.py         # 로그인, 회원가입, 로그아웃 뷰
│   ├── admin_views.py   # 관리자 사용자 관리 뷰
│   ├── forms.py         # Django 폼
│   └── urls.py          # URL 패턴
├── chat/                # 채팅 앱
│   ├── models.py        # Chatroom, Chat, ChatSource 모델
│   ├── views.py         # 채팅 뷰
│   ├── services.py      # Chat API 연동 서비스
│   └── urls.py          # URL 패턴
├── templates/           # Django 템플릿
└── static/              # 정적 파일
```

### 2. 데이터베이스 모델 변경

#### User 모델
- `AbstractBaseUser`와 `PermissionsMixin` 상속
- `user_id` → `username` 필드명 변경 (primary key)
- bcrypt 비밀번호 해싱 호환 유지
- `is_admin`, `is_disabled`, `is_deleted` 필드 유지

#### Chat 모델
- `Chatroom.user` ForeignKey의 `to_field='username'` 지정
- 기존 데이터베이스 스키마 호환성 유지

### 3. 템플릿 문법 수정

#### Jinja2 → Django 템플릿 변환
- `{{ user.name[:1] }}` → `{{ user.name|slice:":1" }}` (Python slicing → Django filter)
- `{{ 'active' if active == 'chat_new' }}` → `{% if active == 'chat_new' %}active{% endif %}` (조건식)
- `{% url %}` 태그로 URL 라우팅
- `{% csrf_token %}` 추가 (POST 폼 보호)

### 4. URL 구조 정리

#### 중복 제거
- `/login/login/` → `/login/` (users/urls.py에서 `login/` 제거)
- Django 기본 admin(`/admin/`)과 커스텀 admin(`/admin/users/`, `/admin/documents/`, `/admin/stats/`) 순서 조정

#### HTTP 메서드 기반 라우팅 해결
Django는 FastAPI와 달리 동일 URL에서 HTTP 메서드 기반 라우팅을 지원하지 않으므로 경로 분리:
- `/chat/api/rooms` (GET) → 유지
- `/chat/api/rooms` (POST) → `/chat/api/rooms/create`
- `/chat/api/rooms/<id>/messages` (GET) → 유지
- `/chat/api/rooms/<id>/messages` (POST) → `/chat/api/rooms/<id>/messages/send`
- `/chat/api/rooms/<id>` (DELETE) → `/chat/api/rooms/<id>/delete`
- `/admin/users/api/<id>` (PATCH) → `/admin/users/api/<id>/update`
- `/admin/users/api/<id>` (DELETE) → `/admin/users/api/<id>/delete`

### 5. JavaScript 수정

#### CSRF 토큰 추가
모든 POST/PATCH/DELETE 요청에 `X-CSRFToken` 헤더 추가:
```javascript
headers: {
    "X-CSRFToken": getCookie('csrftoken')
}
```

#### URL 업데이트
- `/chat/api/rooms` (POST) → `/chat/api/rooms/create`
- `/chat/api/rooms/<id>/messages` (POST) → `/chat/api/rooms/<id>/messages/send`
- `/chat/api/rooms/<id>` (DELETE) → `/chat/api/rooms/<id>/delete`
- `/admin/users/api/<id>` (PATCH) → `/admin/users/api/<id>/update`
- `/admin/users/api/<id>` (DELETE) → `/admin/users/api/<id>/delete`

### 6. 설정 파일 변경

#### config/settings.py
- Django 앱 등록 (`users`, `chat`)
- 커스텀 User 모델 지정 (`AUTH_USER_MODEL = 'users.User'`)
- 환경 변수 로드 (python-dotenv)
- 데이터베이스 설정 (MySQL/SQLite)
- 정적/미디어 파일 설정
- 세션 쿠키 만료 설정 (3시간)
- 외부 API URL 설정 (CHAT_API_BASE_URL, DOC_API_BASE_URL)

## 실행 방법

### 1. 의존성 설치

```bash
# Django 웹 서버
cd web
pip install -r requirements.txt

# RAG 서버
cd ../RAG
pip install -r requirements.txt

# LLM 서버
cd ../LLM
pip install -r requirements.txt
```

### 2. 환경 변수 설정

#### Django 웹 서버 (.env)
```bash
cd web
# .env 파일 생성 (.env.example 참조)

# MySQL 사용 시:
DATABASE_URL=mysql+pymysql://root:1234@localhost:3306/rag_chatbot?charset=utf8mb4

# SQLite 사용 시 (개발용):
DATABASE_URL=sqlite:///./db.sqlite3

# 공통 설정:
SESSION_SECRET_KEY=django-insecure-random-secret-key
CHAT_API_BASE_URL=http://localhost:8002
CHAT_API_TIMEOUT_SECONDS=15
DOC_API_BASE_URL=http://localhost:8001
```

#### RAG 서버 (config.py)
```python
# RAG/config.py 파일에서 데이터베이스 설정 확인
DB_HOST = "localhost"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "1234"
DB_NAME = "rag_chatbot"
```

#### LLM 서버 (.env)
```bash
cd LLM
# .env 파일 생성 (.env.example 참조)
LLM_SERVICE_PORT=8002
OPENAI_API_KEY=your-openai-api-key
RAG_API_BASE_URL=http://localhost:8001
```

### 3. 데이터베이스 마이그레이션

```bash
cd web
python manage.py makemigrations
python manage.py migrate
```

### 4. 서버 실행

세 개의 터미널에서 각 서버를 실행합니다:

**터미널 1 - Django 웹 서버 (포트 8000):**
```bash
cd web
python run.py
```

**터미널 2 - RAG 서버 (포트 8001):**
```bash
cd RAG
python app.py
```

**터미널 3 - LLM 서버 (포트 8002):**
```bash
cd LLM
python -m app.main
```

### 5. 슈퍼유저 생성 (선택)

```bash
cd web
python manage.py createsuperuser
```

## URL 구조

### 인증
- `GET /login` - 로그인 페이지
- `POST /login/auth/login` - 로그인 제출
- `GET /login/auth/check-user-id` - 아이디 중복 확인
- `POST /login/auth/signup` - 회원가입
- `POST /login/auth/logout` - 로그아웃

### 채팅
- `GET /chat` - 새 대화 페이지
- `GET /chat/<chatroom_id>` - 대화방 페이지
- `GET /chat/api/rooms` - 대화방 목록
- `POST /chat/api/rooms/create` - 대화방 생성
- `GET /chat/api/rooms/<chatroom_id>/messages` - 메시지 목록
- `POST /chat/api/rooms/<chatroom_id>/messages/send` - 메시지 전송
- `DELETE /chat/api/rooms/<chatroom_id>/delete` - 대화방 삭제

### 관리자 - 사용자
- `GET /admin/users` - 사용자 관리 페이지
- `GET /admin/users/api/list` - 사용자 목록 API
- `POST /admin/users/api/create` - 사용자 생성
- `PATCH /admin/users/api/<user_id>/update` - 사용자 수정
- `DELETE /admin/users/api/<user_id>/delete` - 사용자 삭제

### 관리자 - 문서
- `GET /admin/documents` - 문서 관리 페이지

### 관리자 - 통계
- `GET /admin/stats` - 통계 페이지
- `GET /admin/stats/api/summary` - 통계 요약 API

## 주의사항

### 503 Service Unavailable 에러
채팅 메시지 전송 시 503 에러가 발생하는 경우:
- `CHAT_API_BASE_URL` 환경 변수가 설정되어 있는지 확인
- LLM 서버 (포트 8002)가 실행 중인지 확인
- RAG 서버 (포트 8001)가 실행 중인지 확인

이 에러는 Django 마이그레이션 문제가 아니며, 외부 API 서비스 연결 문제입니다.

### 의존성 충돌 해결
RAG 서버 실행 시 의존성 충돌이 발생할 경우:
```bash
cd RAG
pip install "protobuf>=6.31.1"
pip install "numpy>=2.0.0"
```

### 파일 업로드 Vector DB 적재
파일 업로드 시 Vector DB 적재가 실패하더라도 파일은 데이터베이스에 저장됩니다. embedding 모델 의존성 문제로 인해 Vector DB 적재가 실패할 수 있지만, 이는 파일 업로드 기능에 영향을 주지 않습니다.

### 데이터베이스 호환성
- 기존 FastAPI 애플리케이션의 데이터베이스를 그대로 사용할 수 있습니다.
- `user_id` 컬럼이 Django의 `username` 필드로 매핑됩니다.
- bcrypt로 해싱된 비밀번호는 호환됩니다.

### 세션 관리
- 세션 만료 시간: 3시간 (설정에서 변경 가능)
- 세션 만료 시 `/login?expired=1`로 리다이렉트

## 테스트 체크리스트

- [ ] 로그인 페이지 접속 (`/login`)
- [ ] 회원가입 기능
- [ ] 로그인 기능
- [ ] 로그아웃 기능
- [ ] 채팅 페이지 접속 (`/chat`)
- [ ] 대화방 생성
- [ ] 메시지 전송 (LLM 서버 필요)
- [ ] 대화방 삭제
- [ ] 관리자: 사용자 관리 페이지 (`/admin/users`)
- [ ] 관리자: 문서 관리 페이지 (`/admin/documents`)
- [ ] 관리자: 통계 페이지 (`/admin/stats`)

## 기술 스택

- **Framework**: Django 6.1
- **Database**: MySQL 8.0 (또는 SQLite)
- **Template Engine**: Django Template
- **Authentication**: Django Auth + bcrypt
- **HTTP Client**: httpx (외부 API 연동)
- **Static Files**: Django static files

## 추가 정보

- Django 기본 관리자: `/admin/`
- 정적 파일: `/static/`
- 미디어 파일: `/media/`
