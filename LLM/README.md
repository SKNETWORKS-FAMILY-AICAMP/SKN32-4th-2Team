# Smart HR LLM Service

사내 HR 규정 질의에 대한 답변 생성, 주제 분류, 채팅방 제목 생성을 제공하는 FastAPI 서비스입니다.
이 서비스는 상태를 저장하지 않습니다. 사용자·채팅·세션 저장은 Django WEB이, 문서 검색과 인덱스 관리는 별도 RAG 서비스가 담당합니다.

~~~text
Django WEB  →  LLM FastAPI  →  RAG FastAPI
                    │
                    └─ OpenAI 또는 Gemini
~~~

## 운영 범위

- 운영 API에서 선택할 수 있는 프로바이더는 OpenAI와 Gemini뿐입니다.
- Qwen 코드는 qwen-sft/ 아래의 연구·파인튜닝·벤치마크 트랙에만 남깁니다. WEB 또는 공개 API에서 provider=qwen으로 호출할 수 없습니다.
- RAG 검색이 실패하면 답변 API는 500 대신 rag_degraded=true와 빈 sources를 반환합니다. Django는 이를 사용자에게 일시 장애로 안내해야 합니다.
- API 계약의 기준 문서는 docs/API.md이며, FastAPI 자동 문서는 /docs에서 볼 수 있습니다.

## 주요 API

| Method | Path | 용도 |
| --- | --- | --- |
| POST | /v1/chat | 답변, 주제, 근거 문서를 한 번에 생성 |
| POST | /v1/chatroom-name | 첫 질문으로 채팅방 제목 생성 |
| POST | /v1/topic | 배치·관리용 주제 재분류 |
| GET | /health | 프로바이더 및 RAG 연결 상태 확인 |
| GET | /docs | Swagger 문서 |

일반 채팅 흐름에서는 /v1/chat만 호출합니다. /v1/topic을 추가로 부르면 불필요한 LLM 호출이 하나 더 발생합니다.

## 로컬 실행

Python 3.11 기준입니다.

~~~powershell
cd D:\SKN32-4th-2Team\LLM
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.main
~~~

.env에는 실제 API 키만 채웁니다. .env와 가상환경은 Git에 포함하지 않습니다.

## 최소 환경 설정

~~~dotenv
LLM_SERVICE_PORT=8002
LLM_MODE=live
DEFAULT_PROVIDER=openai
OPENAI_API_KEY=실제_키
OPENAI_MODEL=gpt-4o-mini

RAG_MODE=live
RAG_BASE_URL=http://127.0.0.1:8001
RAG_TIMEOUT_SEC=45
RAG_TOP_K=5
ANSWER_CITE_ARTICLES=true
~~~

키 없이 화면·연동 흐름만 확인할 때는 LLM_MODE=mock을 사용합니다. 실제 RAG 검색을 확인하려면 RAG_MODE=live를 유지합니다.

## 4차 프로젝트 통합 예시

로컬에서 세 서비스를 동시에 띄울 때 아래 포트를 기준으로 맞춥니다.

| 서비스 | 설정 | 예시 값 |
| --- | --- | --- |
| Django WEB | CHAT_API_BASE_URL | http://127.0.0.1:8002 |
| Django WEB | DOC_API_BASE_URL | http://127.0.0.1:8001 |
| LLM | LLM_SERVICE_PORT | 8002 |
| LLM | RAG_BASE_URL | http://127.0.0.1:8001 |
| RAG | RAG_API_PORT | 8001 |

실행 순서는 RAG, LLM, Django WEB입니다. 배포 환경에서는 127.0.0.1 대신 서비스 이름 또는 내부 DNS를 사용합니다.

확인 순서:

1. RAG의 /health와 LLM의 /health가 정상인지 확인합니다.
2. LLM /v1/chat에 짧은 HR 질문을 보내 sources가 반환되는지 확인합니다.
3. Django에 로그인한 뒤 새 대화에서 같은 질문을 보내 답변, 채팅 저장, 근거 문서 표시를 함께 확인합니다.

## 조문 인용 설정

최신 RAG의 조문 머리 청킹·대상 인덱스 재적재·WEB → LLM → RAG E2E 검증이 완료되어, 현재 통합 구성은 `ANSWER_CITE_ARTICLES=true`를 사용합니다. `strip_unverifiable_citations`가 검색 문맥에 없는 조 번호는 계속 제거하므로, 답변에 남는 조문 번호는 검색 근거와 대조됩니다.

CPU 환경의 RAG 검색은 약 15~26초가 측정됐습니다. GPU 전환 전 개발·시연 환경에서는 `RAG_TIMEOUT_SEC=45`를 사용하고, GPU 성능 측정 후 서비스 수준에 맞게 낮춥니다.

## 성능 측정 기준

하나의 채팅 요청은 RAG 검색 후 답변 생성과 주제 분류를 병렬로 처리합니다. 따라서 전체 시간은 RAG 시간과 두 LLM 작업 중 느린 작업의 합에 가깝습니다.

성능 비교 시에는 다음을 함께 기록합니다.

- 질문과 검색 대상 문서 집합
- RAG CPU 또는 GPU 실행 여부
- RAG 검색 시간, 답변 생성 시간, 주제 분류 시간, 전체 응답 시간
- 모델·프롬프트·RAG 파이프라인 버전
- 근거 문서와 조문 인용의 정확성

계측 로그와 벤치마크 원본 결과는 로컬 산출물로 두고, 검토가 끝난 요약 보고서만 커밋합니다.

## Git 반영 범위

커밋 대상은 운영 코드, API 계약, .env.example, 검증된 문서와 테스트입니다. 다음은 커밋하지 않습니다.

- API 키와 .env
- 가상환경, 캐시, 로그, 로컬 벤치마크 원본
- Qwen 가중치, 변환 모델, 생성 데이터와 대용량 결과물
- django_llm/ 및 run_django.py 같은 FastAPI-to-Django 비교 실험 파일

## 참고 문서

- docs/API.md: WEB이 호출하는 요청·응답·오류 계약
- docs/RAG_FEEDBACK.md: RAG 청킹·조문 인용 연동 조건
- docs/WEB_INTEGRATION_REPORT.md: WEB 연동 점검 이력
- qwen-sft/README.md: Qwen 연구 트랙
