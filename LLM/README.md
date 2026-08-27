# Smart HR LLM Service

답변 생성, 주제 분류, 채팅방 제목 생성을 제공하는 FastAPI 서비스입니다. 상태를 저장하지 않으며, 사용자·채팅 데이터는 Django WEB이, 문서 검색과 FAISS 인덱스는 RAG 서비스가 담당합니다.

```text
Django WEB (8000) → LLM (8002) → RAG (8001) → MySQL + FAISS
```

LLM은 MySQL에 직접 연결하지 않습니다. 대상 DB는 WEB의 `DATABASE_URL`과 RAG의 `RAG_DB_NAME`이 함께 가리키는 신규 DB `rag_chatbot_v4`이며, LLM에는 이 두 변수나 `LEGACY_DATABASE_URL`을 설정하지 않습니다.

새 환경의 MySQL 마이그레이션과 PDF 색인은 [전체 실행 가이드](../SETUP.md)를 먼저 완료해야 합니다. 이전 DB를 보유한 팀원은 WEB에서 사용자·채팅 데이터와 과거 근거 표시 스냅샷인 `chat_source`만 일회성 이관하고, RAG는 현재 `RAG/res/pdf`를 기준으로 새 `vector_store`를 생성합니다. RAG 부트스트랩 전에는 LLM이 기동되어도 검색 요청이 `No vector store found`로 실패하고, 응답은 `rag_degraded=true` 상태가 될 수 있습니다. RAG의 `Application startup complete`와 `/health`의 `models_ready: true`를 확인한 뒤 LLM을 시작하면 첫 질문이 모델 적재를 떠안지 않습니다.

## API

| Method | Path | 용도 |
| --- | --- | --- |
| `GET` | `/health` | 프로바이더와 RAG 연결 상태 확인 |
| `POST` | `/v1/chat` | 답변·주제·근거 문서를 한 번에 생성 |
| `POST` | `/v1/chatroom-name` | 첫 질문으로 채팅방 제목 생성 |
| `POST` | `/v1/topic` | 관리·배치용 주제 재분류 |
| `GET` | `/docs` | Swagger API 문서 |

일반 채팅 흐름에서는 `/v1/chat`만 호출합니다. 답변 API는 RAG 검색이 일시적으로 실패해도 서비스 자체를 500으로 끝내지 않고, `rag_degraded`와 빈 `sources`를 내려줄 수 있습니다.

`POST /v1/chat/stream`(SSE)은 현재 미사용 상태로 남겨 둔 실험 경로입니다.

전체 스택(web·rag·llm·nginx)을 한 번에 띄우는 Docker Compose 배포는 레포 루트에서 실행하며, 그 절차는 루트 README와 [SETUP.md](../SETUP.md)를 따릅니다. 아래는 컨테이너 없이 LLM만 로컬(venv)에서 직접 실행하는 절차입니다.

## 환경 준비

```powershell
cd D:\Dev_Tools\SKN32-4th-2Team\LLM
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

실제 API 키와 환경별 값은 `.env`에만 작성합니다. `.env`는 커밋하지 않습니다.

| 변수 | 통합 기준값 또는 용도 |
| --- | --- |
| `LLM_SERVICE_PORT` | `8002` |
| `LLM_MODE` | 실제 API는 `live`, 화면 흐름만 확인할 때는 `mock` |
| `DEFAULT_PROVIDER` | `openai` 또는 `gemini` |
| `LLM_TIMEOUT_SEC` | 답변·주제·채팅방 이름 프로바이더 호출 제한 `15초` |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` | 실제 프로바이더 키 |
| `RAG_MODE` | RAG를 쓸 때 `live` |
| `RAG_BASE_URL` | `http://127.0.0.1:8001` |
| `RAG_TIMEOUT_SEC` | CPU 테스트 시 충분히 큰 값 사용(기본 예시 45초) |
| `RAG_TOP_K` | LLM에 넘길 최종 문서 수 |
| `ANSWER_CITE_ARTICLES` | 문서-조문 귀속 검증 전에는 `false` 유지. 화면에는 검증된 근거 문서가 별도 표시됨 |
| `ANSWER_VERIFY_MODE` | `risky` 권장. 급여·휴직·징계 등만 의미적 근거 검증 (`off`/`all` 선택 가능) |

## 첫 실행과 일반 실행

새 PC·새 DB라면 아래 순서가 선행되어야 합니다. 이전 DB가 없는 팀원은 2단계 뒤 바로 4단계로 진행합니다.

1. WEB의 `DATABASE_URL`과 RAG의 `RAG_DB_NAME`을 같은 신규 DB `rag_chatbot_v4`로 준비하고, 세 서비스의 나머지 `.env`를 작성합니다. LLM에는 DB URL을 넣지 않습니다.
2. `web/manage.py migrate --noinput`으로 공용 테이블을 만듭니다.
3. 이전 DB 보유자만 `web/.env`의 `LEGACY_DATABASE_URL`로 사용자·채팅 데이터와 `chat_source` 스냅샷을 이관합니다. 이 설정은 LLM에 추가하지 않으며, document·PDF·FAISS 인덱스는 이관하지 않습니다.
4. `RAG/scripts/bootstrap_documents.py --apply`로 현재 `RAG/res/pdf`에서 document 등록과 새 FAISS 색인을 만듭니다.
5. RAG → LLM → Django 순으로 서버를 실행합니다.

LLM 서버 자체의 실행 명령은 다음과 같습니다.

```powershell
cd D:\Dev_Tools\SKN32-4th-2Team\LLM
.\.venv\Scripts\python.exe -m app.main
```

실행 후 `http://127.0.0.1:8002/docs` 또는 `/health`에서 확인합니다. 최초 부트스트랩이 완료된 같은 PC·같은 DB에서는 이후 LLM을 포함한 세 서버만 다시 켜면 됩니다.

## 성능 비교

CPU/GPU 또는 검색 후보 수 비교 시에는 같은 PDF 코퍼스와 같은 FAISS 인덱스·질문 세트를 사용합니다. `RAG_DEVICE=cpu` 또는 `RAG_DEVICE=cuda`는 RAG 환경에서 설정하며, LLM 로그의 RAG 시간과 답변 생성 시간을 분리해 기록합니다. 청킹·임베딩 모델·조문 머리 설정을 바꾸면 RAG에서 재색인한 뒤 비교합니다.

## 개발 범위

운영 API의 프로바이더는 OpenAI와 Gemini입니다. `qwen-sft/`는 별도의 연구·파인튜닝·벤치마크 트랙이며, 공개 웹 API의 프로바이더로 사용하지 않습니다.

## 관련 문서

- [전체 실행 가이드](../SETUP.md)
- [RAG API·운영 문서](../RAG/README.md)
- [WEB 연동 문서](../web/README.md)
- [API 계약](docs/API.md)
