# SKN32-4th-2Team

# Smart HR — RAG 기반 사내 규정 질의응답 서비스

사내 구성원이 인사·행정 규정 및 내부 문서를 기반으로 질문하면,
**RAG(Retrieval-Augmented Generation) 기술로 실제 규정 문서를 검색해 근거 기반 답변을 제공하는 AI 행정 지원 서비스**입니다.

일반적인 LLM은 공개된 지식은 알고 있지만, 기관별 내부 규정·업무 절차·행정 문서는 학습되어 있지 않습니다.

본 서비스는 사내 규정 문서를 검색 가능한 지식 데이터로 구축하고,
질문 시 관련 문서를 찾아 LLM에 함께 제공함으로써 **환각(Hallucination)을 줄이고 신뢰 가능한 답변**을 제공합니다.

<br><br>

<!--
발표 자료 / 서비스 화면 스크린샷을 여기에 추가하세요.
예)
<img width="1912" height="1073" alt="시스템 소개" src="이미지_URL" />
-->

<br><br>

---

# 프로젝트 개요

## 문제 상황

사내 구성원은 다음과 같은 문의를 반복적으로 합니다.

* 휴가 및 복무 관련 규정
* 연구년 / 휴직 신청 조건
* 출장 및 행정 처리 절차
* 각종 내부 규정 확인
* 담당 부서 및 처리 방법 문의

하지만 기존 방식은:

```
질문 발생
 ↓
규정 문서 직접 검색
 ↓
담당 부서 문의
 ↓
답변 대기
```

와 같은 비효율적인 과정을 거칩니다.

---

## 해결 방법

```
사용자 질문
      ↓
관련 규정 문서 검색 (RAG)
      ↓
검색 결과 기반 LLM 답변 생성
      ↓
답변 + 근거 문서 제공
```

방식을 통해 사용자가 자연어로 질문하고 즉시 규정 기반 답변을 받을 수 있도록 구현했습니다.

---

# 시스템 아키텍처

```text
                     사내 구성원 (브라우저)
                            │
                    Nginx Reverse Proxy (:80)
                 /  ·  /rag/  ·  /llm/  ·  /static/
                            │
                            ▼
                  WEB Service · Django (8000)
          로그인 / 채팅 / 관리자 / 데이터 저장(MySQL)
                            │
                            ▼
                  LLM Service · FastAPI (8002)
          답변 생성 / 주제 분류 / 채팅 제목 생성
                            │
                            ▼
                  RAG Service · FastAPI (8001)
          문서 관리 / 임베딩 / 검색 / 재정렬
                            │
                            ▼
                MySQL 8.0  +  FAISS Vector Store
                            │
                            ▼
                  사내 규정 및 행정 문서 (PDF)
```

세 서비스는 각각 독립 컨테이너로 동작하며, `docker compose`로 한 번에 기동합니다.
외부에는 Nginx(:80)만 노출되고, 사용자 요청은 경로에 따라 WEB·RAG·LLM으로 프록시됩니다.

---

# 서비스 구성

## 1. WEB Service · Django (Port : 8000)

사내 구성원이 사용하는 웹 서비스 영역입니다.

### 담당 기능

* 사용자 인증 / 세션 관리
* 채팅 화면 제공
* 대화 이력 저장·관리
* 관리자 기능 (사용자 / 문서 / 통계)
* 문서 관리 화면 ↔ RAG 연동

### 주요 기능

**사용자**

* 회원가입 / 로그인
* AI 규정 질의응답
* 채팅방 관리
* 답변 근거 문서 확인

**관리자**

* 사용자 관리
* 규정 문서 관리 (RAG API 연동)
* 문의 통계 확인

### 기술 스택

* Django 5.2 (WSGI / gunicorn)
* Django ORM
* Django Templates (Server Side Rendering)
* 커스텀 사용자 모델 · bcrypt 비밀번호 처리
* MySQL 8.0
* JavaScript / CSS

---

## 2. LLM Service · FastAPI (Port : 8002)

AI 답변 생성과 자연어 처리 영역을 담당합니다.
사용자의 질문과 RAG 검색 결과를 기반으로 답변을 생성하며, **상태를 저장하지 않는 Stateless 서비스**입니다.

### 주요 역할

* 규정 기반 답변 생성
* 문의 주제 분류
* 채팅방 제목 생성
* LLM Provider 관리 / 추상화

지원 Provider:

* OpenAI
* Gemini

> Qwen(Ollama)은 운영 API에는 연결하지 않고, 별도의 파인튜닝·연구 트랙(`LLM/qwen-sft/`)에서만 사용합니다.

### 답변 생성 흐름

```text
사용자 질문
      ↓
RAG 서비스 요청
      ↓
관련 규정 검색 결과 수신
      ↓
질문 + 검색 문서 Prompt 구성
      ↓
LLM 답변 생성
      ↓
주제 분류
      ↓
WEB 서비스 반환
```

### 주제 분류 설계

관리자 통계 활용을 위해 LLM이 주제를 자유롭게 생성하게 하지 않고,
고정 카테고리 기반 분류 방식을 적용했습니다.

```
"휴가 며칠 사용할 수 있나요?"
"연차 기준 알려주세요"
"휴가 규정 궁금합니다"
```

같은 질문은 모두 `휴가/휴직`으로 저장됩니다.

```
Enum 제약 출력
        ↓
화이트리스트 검증
        ↓
정규화 캐시
        ↓
DB 저장
```

이를 통해 통계 데이터의 일관성을 유지합니다.

---

## 3. RAG Service · FastAPI (Port : 8001)

사내 규정 문서를 관리하고 검색하는 지식 기반 서비스입니다.

### 주요 역할

* PDF 문서 관리 (업로드 / 색인 / 소프트 삭제)
* 문서 텍스트 추출
* Chunk 분할
* Embedding 생성
* Vector 검색
* 검색 결과 재정렬

### RAG Pipeline

```text
사내 규정 PDF
       ↓
텍스트 추출
       ↓
Chunk Split
       ↓
Embedding 생성
       ↓
FAISS 저장
       ↓
사용자 질문 Vector 검색
       ↓
BM25 + Vector Search
       ↓
Reranker 재정렬
       ↓
LLM 전달
```

### 기술 스택

* FastAPI
* MySQL (mysql-connector-python)
* FAISS
* sentence-transformers
* BM25 (rank-bm25)
* Cross Encoder Reranker
* LangChain (텍스트 분할 파이프라인)

Embedding:

```
jhgan/ko-sroberta-multitask
```

Reranker:

```
BAAI/bge-reranker-v2-m3
```

---

# RAG를 적용한 이유

일반 LLM은 기관 내부 규정을 알 수 없습니다.

```
질문:
"연구년 신청 기준이 어떻게 되나요?"
```

일반 LLM:

```
기관마다 다르므로 확인이 필요합니다.
```

또는 학습 데이터 기반으로 잘못된 답변을 생성할 수 있습니다.

RAG 적용:

```
질문
 ↓
사내 규정 검색
 ↓
실제 문서 전달
 ↓
근거 기반 답변 생성
```

따라서 기관별 규정과 절차를 반영한 정확한 답변이 가능합니다.

---

# 프로젝트 구조

```text
SKN32-4th-2Team/
├── web/                       # WEB 서비스 · Django (8000)
│   ├── config/                # settings / urls / wsgi · asgi
│   ├── users/                 # 인증·회원가입·관리자(사용자/문서/통계)
│   ├── chat/                  # 채팅방·메시지·LLM 호출
│   ├── documents/             # document 모델·마이그레이션
│   ├── legacy_import/         # 레거시 DB 일회성 이관
│   ├── templates/  static/
│   ├── manage.py
│   └── README.md
│
├── LLM/                       # LLM 서비스 · FastAPI (8002)
│   ├── app/
│   │   ├── providers/         # openai / gemini / mock
│   │   ├── routers/           # chat / meta
│   │   └── services/          # answer / topic / grounding ...
│   ├── qwen-sft/              # 파인튜닝·연구 트랙
│   ├── bench/
│   └── README.md
│
├── RAG/                       # RAG 서비스 · FastAPI (8001)
│   ├── app.py
│   ├── rag_pipeline.py
│   ├── scripts/               # bootstrap_documents.py 등
│   ├── res/pdf/               # 규정 PDF 코퍼스
│   ├── vector_store/          # PC별 FAISS 인덱스 (Git 제외)
│   └── README.md
│
├── nginx/                     # 리버스 프록시 설정
├── scripts/                   # 배포 보조 스크립트
├── docker-compose.yml         # 전체 스택 오케스트레이션
├── SETUP.md                   # 팀 실행 가이드 (정본)
└── README.md
```

---

# 실행 방법

## 방법 A. Docker로 한 번에 실행 (권장)

레포 루트에서 세 서비스(web · rag · llm)와 Nginx를 한 번에 기동합니다.

```bash
docker compose up -d --build
```

접속: `http://localhost`

기동 순서는 healthcheck로 `web → rag → llm → nginx` 가 보장됩니다.
RAG는 모델 적재와 최초 PDF 부트스트랩 때문에 첫 기동이 다소 오래 걸립니다.

---

## 방법 B. 로컬(venv) 첫 실행 — 처음 실행하는 분들

Windows PowerShell 기준입니다. 처음 실행하는 팀원은 아래 순서를 그대로 따라갑니다.

### 1. 준비물

* Python 3.11
* MySQL 8 이상, 비어 있는 데이터베이스 `rag_chatbot_v4`
* 실제 LLM 테스트 시 OpenAI 또는 Gemini API 키

DB가 없으면 한 번만 생성합니다.

```sql
CREATE DATABASE rag_chatbot_v4 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 2. 가상환경 · 환경변수(.env)

서비스마다 가상환경을 만들고 `.env.example`을 복사해 실제 값을 채웁니다.

```powershell
cd web
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

세 `.env`는 같은 MySQL을 바라봐야 합니다.

| 파일 | 확인할 값 |
| --- | --- |
| `web/.env` | `DATABASE_URL`의 DB명 = `rag_chatbot_v4`, `CHAT_API_BASE_URL=http://127.0.0.1:8002`, `DOC_API_BASE_URL=http://127.0.0.1:8001` |
| `RAG/.env` | `RAG_DB_*`가 같은 MySQL의 `rag_chatbot_v4`, `RAG_API_PORT=8001` |
| `LLM/.env` | `RAG_BASE_URL=http://127.0.0.1:8001`, 실제 테스트 시 LLM API 키 |

### 3. DB 마이그레이션

```powershell
cd web
.\.venv-django\Scripts\python.exe manage.py migrate --noinput
```

이 명령이 `document`를 포함한 공용 테이블을 만듭니다. 과거 SQL 파일(`RAG/sql/rag_document.sql`, `sql/rag_chatbot_schema.sql`)은 실행하지 않습니다.

### 4. (선택) 기존 MySQL 데이터 이관

**이전 MySQL DB를 보유한 팀원만** 사용자·채팅 이력을 이관합니다. 절차는 [SETUP.md](SETUP.md)의 "기존 DB 데이터 이관"을 참고하세요. 이전 DB가 없으면 이 단계를 건너뜁니다.

### 5. PDF 등록 · FAISS 색인 (부트스트랩)

`RAG/res/pdf`의 규정 PDF를 `document` 행으로 등록하고 검색 인덱스를 만듭니다. 기본 실행은 미리보기이고, `--apply`에서만 실제 기록됩니다.

```powershell
cd RAG
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply
```

> PDF를 폴더에 넣기만 해서는 검색되지 않습니다. 위 부트스트랩이 등록과 색인을 함께 수행합니다.

### 6. 서버 실행 (RAG → LLM → WEB)

RAG 창에서 `Application startup complete`가 나온 뒤 다음 서버를 켭니다.

```powershell
# 창 1 — RAG
cd RAG
.\.venv\Scripts\python.exe app.py

# 창 2 — LLM
cd LLM
.\.venv\Scripts\python.exe -m app.main

# 창 3 — WEB
cd web
.\.venv-django\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

브라우저에서 `http://127.0.0.1:8000`으로 접속합니다.

### 7. 동작 확인

* `http://127.0.0.1:8001/health` — RAG 상태
* `http://127.0.0.1:8002/health` — LLM · RAG 연결 상태
* Django 로그인 후 질문 → 답변과 근거 문서 표시 확인

> 재색인 조건, 트러블슈팅 등 상세 운영 절차는 [SETUP.md](SETUP.md)를 참고하세요.

---

# 주요 설계 포인트

## 1. 서비스 분리 구조

WEB / LLM / RAG를 독립 서비스로 분리했습니다.

* 서비스별 독립 개발 가능
* 장애 영향 최소화
* 모델 교체 용이
* API 계약 기반 확장 가능

## 2. Stateless LLM 구조

LLM 서비스는 DB를 직접 관리하지 않습니다.

```
Request
 ↓
AI 처리
 ↓
JSON Response
```

저장과 관리는 WEB(Django) 서비스에서 담당합니다.

## 3. 검색 품질 개선

단순 Vector Search가 아닌:

```
Vector Search
+
BM25 Keyword Search
+
Reranker
```

구조를 적용하여 검색 정확도를 개선했습니다.

## 4. Django 전환 · 컨테이너 배포

* WEB 계층을 Django로 구성하고, 공용 `document` 테이블의 마이그레이션 소유권을 Django가 가집니다.
* 세 서비스가 같은 MySQL `rag_chatbot_v4`를 바라보며, RAG는 스키마를 자동 생성하지 않습니다.
* `docker compose` + Nginx 리버스 프록시로 전체 스택을 한 번에 배포합니다.

## 5. 운영 고려 사항

* API Error 규격 통일
* Timeout 처리
* Provider 추상화 / Mock 모드 지원
* 성능 측정(bench) 환경 구성
* 개인정보 로그 보호
* 근거 기반 답변(Grounding) 처리

---

# 테스트 결과물

통합 테스트 계획·판정은 [프로젝트 통합 테스트 계획 및 결과 보고서](산출물/프로젝트_통합_테스트_계획_및_결과_보고서_20260826.md)에 정리돼 있고,
그 근거가 된 실측 로그·벤치 결과물의 사본을 [`산출물/테스트결과/`](산출물/테스트결과) 폴더에 모아 두었습니다.

```text
산출물/테스트결과/
├── 배포_컨테이너_테스트/         # Docker 배포 실측 로그 (보고서 §6.4)
│   ├── rag-build-test.log        # RAG 이미지 빌드: 157초, 2.94GB/662MB, nvidia-* 미포함(이전 CUDA ~10GB 대비 축소)
│   └── compose-test.log          # 전체 스택 기동: 1차 실패 2건→수정→2차 전 서비스 healthy, /302·/rag/health 200·/llm/health 200
└── 벤치_성능_품질/               # RAG·LLM 성능·품질 벤치 (보고서 §6.2·§6.3)
    ├── 20260826_controlled-summary.json / .csv     # 검색 통제행렬 8조건(CPU FP32 vs CUDA FP16 등)
    ├── 20260826_corpus-manifest.json               # 코퍼스 매니페스트(PDF 93건·청크)
    ├── 20260826_llm_quality_review.csv             # 35문항 수기 품질 등급
    ├── 20260826_llm_quality_summary.json           # LLM 자동 지표 + raw 해시
    ├── 20260826_current_grounding_retest.md        # 근거 안전장치 적용 후 재검수·문항별 판정
    ├── 20260826_current_grounding_summary.json     # 재검수 검색·E2E·수동 품질 요약
    └── 20260826-155538_verify-e2e-grounding_openai.jsonl  # 최신 E2E raw(35문항·CUDA·gpt-4o-mini)
```

각 파일은 원본 위치(`RAG/`, `LLM/`)에도 그대로 있으며, 위 폴더에는 산출물 보존용 사본을 둡니다.
배포 로그는 `RAG/.gitignore`의 `*.log`로 git 미추적이었으며, `b0b8b1a`(2026-08-26 그날 마지막 커밋) +
테스트 중 로컬 수정(`.dockerignore`·`RAG/Dockerfile` CRLF 정규화, 미커밋) 기준으로 기록됐습니다.

---

# 상세 문서

각 서비스 및 실행 관련 상세 내용은 아래 문서를 참고하세요.

| 구분                 | 문서                                                                                 |
|--------------------|------------------------------------------------------------------------------------|
| WEB                | [web/README.md](web/README.md)                                                     |
| LLM                | [LLM/README.md](LLM/README.md)                                                     |
| RAG                | [RAG/README.md](RAG/README.md)                                                     |
| 팀 실행 가이드           | [SETUP.md](SETUP.md)                                                               |
| Django 이관·MySQL 통합 | [README2.md](README2.md)                                                           |
| 통합 테스트 보고서         | [산출물/프로젝트_통합_테스트_계획_및_결과_보고서_20260826.md](산출물/프로젝트_통합_테스트_계획_및_결과_보고서_20260826.md) |
| AWS 배포 가이드         | [AWS배포가이드.md](AWS배포가이드.md)                                                          |

---

# Team Project

사내 규정과 행정 문서를 기반으로
구성원이 쉽고 빠르게 정보를 찾을 수 있도록 지원하는
**RAG 기반 AI 행정 지원 서비스**입니다.
