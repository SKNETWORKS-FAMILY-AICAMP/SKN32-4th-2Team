# Smart HR LLM 서비스: RAG 기반 사내 규정 질의응답

사내 HR 규정을 직원이 평소 말투로 물어보면, **실제 규정 문서를 근거로** 답하는
시스템의 **LLM 파트**입니다. 답변 생성 · 주제 분류 · 채팅방 이름 생성을 담당합니다.

> 담당: Member D · 포트 `8002`

```text
직원 질문
    ↓
WEB 서버 (8000)  화면 · 로그인 · DB 저장
    ↓
LLM 서비스 (8002)  ← 이 저장소
    ├→ RAG 서비스 (8001) 에서 근거 문서 검색
    ├→ 답변 생성 (OpenAI / Gemini / Qwen)
    └→ 주제 분류 (enum 제약 디코딩)
    ↓
답변 + 주제 + 근거 문서를 JSON 으로 반환
    ↓
WEB 이 chat / chat_source 테이블에 저장
```

---

## 핵심 개념

### 왜 RAG 인가

LLM 은 근로기준법 같은 **법령은 알지만 우리 학교 복무규정은 모릅니다.**
학습 데이터에 없기 때문입니다. 그런데 직원이 묻는 것은 대부분 사내 규정입니다.

규정 문서를 안 주고 물어보면 **그럴듯하게 지어냅니다.** 실제로 검증했을 때
"승진 시험은 보통 연초" 라고 답했는데 실제 규정은 **매년 10월**이었습니다.

그래서 질문이 들어올 때마다 규정 문서에서 관련 대목을 찾아 프롬프트에 넣고,
**그 근거로만 답하게** 합니다. 이것이 RAG(Retrieval-Augmented Generation)입니다.

### 왜 서비스를 셋으로 나눴나

WEB · LLM · RAG 를 각각 다른 포트의 독립 서비스로 띄웁니다.

- **동시 개발** — API 계약만 맞추면 넷이 서로를 기다리지 않고 진행할 수 있습니다
- **장애 격리** — RAG 가 죽어도 챗봇 화면은 살아 있습니다
- **교체 용이** — 모델을 바꿔도 WEB 은 아무것도 몰라도 됩니다

**이 서비스는 DB 에 붙지 않습니다(stateless).** 질문을 받아 답변·주제·근거를
JSON 으로 돌려줄 뿐이고, 저장은 WEB 이 합니다.

### 주제를 '생성' 이 아니라 '분류' 로 다루는 이유

관리자 대시보드의 도넛 차트는 `chat.topic` 을 `GROUP BY` 해서 그립니다.
LLM 에게 "주제를 뽑아줘" 하면 "휴가", "연차 문의", "휴가 관련" 처럼 매번 다른
문구가 나와 **차트가 조각나 통계로 쓸 수 없습니다.**

`seed` 고정은 답이 아닙니다. 입력이 완전히 같을 때만 의미가 있는데, 실제 사용자는
"연차 며칠 쓸 수 있나요" / "휴가 얼마나 남았어요" 처럼 매번 다르게 씁니다.

그래서 **안전장치를 세 겹**으로 둡니다.

| 단계 | 방법 | 효과 |
|---|---|---|
| 1 | **enum 제약 디코딩** | 디코더가 목록 밖 토큰을 차단 — 이탈이 구조적으로 불가능 |
| 2 | 화이트리스트 검증 | SDK 동작이 바뀌어도 목록 밖 값은 `기타` 로 |
| 3 | 정규화 해시 캐시 | 같은 문장은 항상 같은 주제. 재현성 + 비용 절감 |

1번은 프롬프트로 "이 중에서 골라줘" 하고 **부탁하는 것이 아닙니다.**
OpenAI Structured Outputs(`strict: true`), Gemini `response_schema`,
Ollama `format` 이 각각 디코딩 단계에서 enum 밖 토큰을 막습니다.

카테고리 8종은 임의로 정한 것이 아니라 실제 규정·법령 PDF 26건을 묶어 도출했습니다.
근거표는 [docs/API.md](docs/API.md) 3절.

---

## 프로젝트 구조

```text
LLM/
├── app/                    서비스 (운영에 실제로 도는 코드)
│   ├── main.py             FastAPI 앱, 기동/종료 훅, 예외 → 에러 규약 변환
│   ├── config.py           .env 로딩. 모든 설정의 단일 출처
│   ├── domain.py           ★ TOPIC_CATEGORIES — 카테고리 바꿀 땐 여기만
│   ├── schemas.py          API 계약의 단일 출처
│   ├── prompts.py          시스템 프롬프트 (튜닝은 여기서만)
│   ├── errors.py           한국어 메시지를 담은 예외
│   ├── metrics.py          지연/토큰 JSONL 기록
│   ├── routers/
│   │   ├── chat.py         POST /v1/chat, /v1/chat/stream
│   │   └── meta.py         POST /v1/topic, /v1/chatroom-name, GET /health
│   ├── providers/          모델 벤더를 감싸는 계층
│   │   ├── base.py         LLMProvider 인터페이스
│   │   ├── openai_provider.py / gemini_provider.py / qwen_provider.py
│   │   ├── mock_provider.py    키 없이 UI 붙여볼 때
│   │   └── registry.py     이름 → 인스턴스, 기동 시 예열
│   └── services/
│       ├── answer.py       ★ 핵심. 검색 → 생성 → 후처리
│       ├── topic.py        주제 분류 + 캐시 + 검증
│       ├── naming.py       채팅방 이름
│       └── rag_client.py   RAG 서비스 HTTP 호출
│
├── bench/                  측정 도구 (운영에 안 쓰임)
│   ├── questions.yaml      평가 문항 35개 + 정답 라벨
│   ├── run_bench.py        문항을 서비스 경로로 돌려 JSONL 기록
│   ├── report.py           JSONL → PERFORMANCE_REPORT.md
│   ├── judge.py            답변이 근거에 뒷받침되는지 채점 (LLM-as-judge)
│   ├── trace_claim.py      근거 없는 문장이 코퍼스에는 있는지 추적
│   ├── variants.py         프롬프트 후보 모음 (A/B 비교용)
│   ├── corpus.py           벤치용 로컬 PDF 검색 (RAG 대역)
│   └── throttle.py         벤치용 호출 속도 제어
│
├── qwen-sft/               곁가지 실험 — Qwen2.5 파인튜닝 (채택 보류)
├── docs/                   문서
├── scripts/                .env.example 드리프트 검사
├── local/                  로컬 실행 스크립트 (git 미포함)
├── logs/                   계측 로그 (git 미포함)
├── .env.example
└── requirements.txt
```

**`app/` 과 `bench/` 를 나눈 것이 이 구조의 핵심입니다.** `bench/` 는 운영 코드를
전혀 건드리지 않고 `app/` 의 함수를 그대로 호출해서 잽니다. 그래서 "벤치에서는
잘 나오는데 실제로는 다르다" 는 일이 생기지 않습니다.

---

## 문서 안내

**코드를 처음 보신다면 [docs/CODE_GUIDE.md](docs/CODE_GUIDE.md) 부터 읽으세요.**

| 문서 | 내용 |
|---|---|
| [docs/CODE_GUIDE.md](docs/CODE_GUIDE.md) | **코드 구조 · 요청 흐름 · 성능 개선 정리** |
| [docs/PERFORMANCE_REPORT.md](docs/PERFORMANCE_REPORT.md) | 측정 결과 (자동 생성) |
| [docs/API.md](docs/API.md) | **제공** — 이 서비스가 노출하는 API → WEB 파트(8000) |
| [docs/RAG_REQUIRED_API.md](docs/RAG_REQUIRED_API.md) | **요청** — 이 서비스가 필요로 하는 API → RAG 파트(8001) |
| [docs/RAG_FEEDBACK.md](docs/RAG_FEEDBACK.md) | 연동하며 발견한 사항 → RAG 파트 |
| [docs/WEB_INTEGRATION_REPORT.md](docs/WEB_INTEGRATION_REPORT.md) | WEB 연동 확인 결과 |
| [qwen-sft/](qwen-sft/) | Qwen2.5 파인튜닝 실험 — **채택 보류**, 근거와 재현 절차 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 08/03 오전 기준 검토 기록 (낡음, 이력용) |

---

# 1단계. 설치

Python **3.11** 을 씁니다. 팀의 세 서비스(WEB·LLM·RAG)를 3.11 로 통일했습니다.

> RAG 쪽 `numpy<2` 때문에 **Python 3.13 에서는 설치가 실패합니다.**

```bash
cd LLM
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
cp .env.example .env            # 값 채우기
```

> ⚠️ **반드시 가상환경에서 설치하세요.** 전역 환경에 바로 설치하면 다른 프로젝트의
> 패키지 버전을 깨뜨릴 수 있습니다.

# 2단계. 환경변수

| 키 | 기본값 | 설명 |
|---|---|---|
| `LLM_MODE` | `live` | `mock` 이면 LLM API 호출 없이 고정 응답 |
| `DEFAULT_PROVIDER` | `openai` | `openai` \| `gemini` \| `qwen` |
| `LLM_TIMEOUT_SEC` | `5.0` | 초과 시 504 + 한국어 안내 (스토리보드 13p 요구사항) |
| `ANSWER_MAX_TOKENS` | `500` | 답변 길이 상한. 프롬프트 지시를 안 지키는 모델 대비 |
| `ANSWER_CITE_ARTICLES` | `false` | 답변에 조문 번호를 넣을지. 현재 RAG 구성에서는 끔 |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | — / `gpt-4o-mini` | |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-3.5-flash` | |
| `QWEN_BASE_URL` / `QWEN_MODEL` | `localhost:11434` / `qwen2.5:7b` | Ollama. 없어도 서비스는 정상 동작 |
| `RAG_MODE` | `mock` | `live` 면 실제 RAG 서비스 호출 |
| `RAG_BASE_URL` | `http://localhost:8001` | |
| `RAG_TIMEOUT_SEC` / `RAG_TOP_K` | `3.0` / `5` | |
| `RAG_MIN_SCORE` | `0.01` | 관련도가 이 값 미만인 검색 결과는 버림 |
| `METRICS_ENABLED` / `METRICS_PATH` | `true` / `logs/metrics.jsonl` | 계측 로그. 성능 보고서 입력 |

`.env` 는 `.gitignore` 에 있으므로 **API 키가 커밋될 일은 없습니다.**

`config.py` 에 설정을 추가했으면 `.env.example` 갱신을 잊지 않도록 확인합니다.

```bash
python scripts/check_env_example.py
```

## API 키 없이 돌려보기

키 발급 전에도 화면을 붙여볼 수 있도록 고정 응답 모드를 넣어 두었습니다.

```bash
# .env
LLM_MODE=mock     # LLM API 호출 안 함
RAG_MODE=mock     # RAG 서비스 호출 안 함
```

**공개 API 계약은 live 모드와 완전히 동일합니다.** 요청 body 로는 선택할 수 없고
환경변수로만 켜지므로 프론트 코드는 mock 여부를 알 필요가 없습니다.

## Qwen(로컬 모델)은 설치하지 않아도 됩니다

프로바이더 셋 중 **Qwen 만 로컬에 [Ollama](https://ollama.com) 가 떠 있어야** 동작합니다.
기본 프로바이더가 `openai` 라 평소 경로는 Qwen 을 전혀 타지 않습니다.

- 서버 기동: 정상 (예열 실패 경고만 로그에 남음)
- `POST /v1/chat`: 정상
- `GET /health`: `"qwen": false` 로 표시
- `provider: "qwen"` 을 **명시해서** 부른 경우에만 `503 LLM_UNAVAILABLE`

굳이 써보려면 4.7GB 를 내려받습니다. 실행 중 VRAM 을 계속 점유합니다.

```bash
ollama pull qwen2.5:7b
```

> **주의** — RAG 리랭커와 Qwen 이 같은 GPU 를 쓰면 8GB 로는 부족합니다.
> Qwen 이 올라가 있으면 RAG 검색이 0.7초 → 8.5초로 느려집니다. 벤치 후에는 내리세요.
>
> ```bash
> curl -s -X POST http://localhost:11434/api/chat -d "{\"model\":\"qwen2.5:7b\",\"messages\":[],\"keep_alive\":0}"
> ```

# 3단계. 실행

```bash
uvicorn app.main:app --reload --port 8002
```

- Swagger: <http://localhost:8002/docs>
- 헬스체크: <http://localhost:8002/health>

세 서비스를 한 번에 띄우려면 (경로는 각자 환경에 맞게 수정):

```bash
powershell -ExecutionPolicy Bypass -File local\start_all.ps1
```

# 4단계. API

자세한 계약은 [docs/API.md](docs/API.md). 요약하면 엔드포인트 4개입니다.

## 4.1 답변 생성 — `POST /v1/chat`

```bash
curl -X POST http://127.0.0.1:8002/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"chatroom_id": "uuid", "message": "유급휴가는 1년에 얼마나 주어지나요?"}'
```

```json
{
  "answer": "유급휴가는 1년간 80퍼센트 이상 출근한 근로자에게 15일이 주어집니다...",
  "topic": "휴가/휴직",
  "sources": [
    {"doc_id": 20, "original_file_name": "복무규정.pdf", "page": 4}
  ],
  "rag_degraded": false
}
```

- `topic` 은 카테고리 8종 중 하나. `chat.topic` 에 그대로 저장하면 됩니다
- `sources` 는 답변 하단 "근거 문서" 표시에 씁니다
- `rag_degraded` 가 `true` 면 검색 실패 상태에서 나온 답변입니다

## 4.2 나머지 엔드포인트

| 엔드포인트 | 용도 |
|---|---|
| `POST /v1/topic` | 주제만 필요할 때 |
| `POST /v1/chatroom-name` | 첫 질문 → 채팅방 제목 (20자 이내) |
| `GET /health` | 프로바이더·RAG 상태 점검 |

## 4.3 에러 규약

에러는 `{"error_code": "...", "message": "..."}` 형태로 통일돼 있고,
`message` 는 **그대로 화면에 출력해도 되는 한국어 문구**입니다.

| 코드 | 상태 | 상황 |
|---|---|---|
| `INVALID_REQUEST` | 422 | 스키마 위반 |
| `LLM_TIMEOUT` | 504 | 생성 타임아웃 |
| `LLM_RATE_LIMITED` | 429 | 벤더 호출 한도 |
| `LLM_UNAVAILABLE` | 503 | 프로바이더 호출 실패 |
| `PROVIDER_NOT_CONFIGURED` | 503 | API 키 미설정 |
| `INTERNAL_ERROR` | 500 | 그 밖 |

# 5단계. 성능 측정

프롬프트를 감으로 고치지 않으려고 **측정 도구를 먼저 만들었습니다.**

## 5.1 평가 문항

`bench/questions.yaml` 에 35문항이 있습니다. 실제 코퍼스에서 뽑았고,
같은 뜻을 다르게 물은 **패러프레이즈 7묶음**과 **범위 밖 질문 3개**를 섞었습니다.

```yaml
- id: leave-annual-a
  question: 연차 며칠까지 쓸 수 있나요?
  category: 휴가/휴직
  sources: ["복무규정.pdf", "5.근로기준법(법률).pdf"]
  group: annual-leave
```

## 5.2 실행

```bash
# 검색이 완벽하다고 가정 — LLM 성능의 상한선
python bench/run_bench.py --provider openai --retrieval corpus

# 실제 RAG 연동 — end-to-end
python bench/run_bench.py --provider openai --retrieval rag

# 프롬프트 변형 비교
python bench/run_bench.py --provider openai --variant catdef2
```

`--retrieval corpus` 는 문항에 라벨된 정답 문서를 직접 줍니다.
**검색 성능을 빼고 모델 능력만** 비교할 때 씁니다. 실제 성능은 `rag` 로 재야 합니다.

## 5.3 집계와 채점

```bash
python bench/report.py                    # → docs/PERFORMANCE_REPORT.md
python bench/judge.py --tag e2e           # 답변이 근거에 뒷받침되는지 (LLM-as-judge)
python bench/trace_claim.py --tag e2e     # 근거 없는 문장이 코퍼스에는 있는지
```

`trace_claim.py` 가 판을 바꿨습니다. "근거 없음" 으로 잡힌 23건 중 **20건(87%)이
코퍼스에는 있는데 검색이 못 찾아온 것**이었습니다. 모델이 지어낸 게 아니라
**검색 문제**였다는 뜻이라, 프롬프트를 더 만지는 대신 RAG 담당자에게 넘길 근거가 됐습니다.

## 5.4 측정 지표

| 지표 | 의미 |
|---|---|
| 주제 정확도 | `chat.topic` 에 저장될 값이 정답 카테고리와 일치한 비율 |
| 묶음 일관성 | 패러프레이즈 묶음이 **하나의** 주제로 수렴한 비율 — 도넛 차트 신뢰도의 근거 |
| 검색 recall | 정답 문서가 검색 결과에 포함된 비율 |
| 지연 p50 / p95 | 스토리보드 13p 의 5초 기준과 비교 |
| 한국어 이탈 | 답변의 한자가 한글의 10% 를 넘는 건수 |
| 조문 인용 오류 | 근거에 없는 조문 번호를 든 건수 |
| 비용 | `logs/metrics.jsonl` 의 실측 토큰으로 환산 |

# 6단계. 결과 요약

전체 수치와 해석은 [docs/PERFORMANCE_REPORT.md](docs/PERFORMANCE_REPORT.md).

## 프로바이더 비교 (35문항 · 동일 조건)

| 모델 | 주제 정확도 | p50 | 한국어 이탈 | 10,000건 비용 |
|---|---|---|---|---|
| OpenAI gpt-4o-mini | 34/35 | 1.8초 | 0건 | 9,869원 |
| Gemini 3.5-flash-lite | 34/35 | 1.2초 | 0건 | 요금 미확인 |
| Qwen2.5:7b 로컬 | 33/35 | 9.7초 | 6건 | 0원 |
| Qwen HR 파인튜닝 | 35/35 | 12.5초 | 0건 | 0원 |

## 개선 이력

| 개선 | 결과 |
|---|---|
| 카테고리에 **경계 정의** 추가 | 주제 분류 **88% → 97%** |
| 답변·주제 동시 실행 (`asyncio.gather`) | 분류 지연이 대기시간에 안 더해짐 |
| 기동 시 예열 | 첫 요청 **약 3초 단축** |
| 출력 토큰 상한 | 최대 지연 **57초 → 13.9초** |
| 습관적 "인사팀 문의" 제거 | **83% → 3%** |
| 관련도 미달 결과 버림 | 근거 없이 답하는 일 없음 |

# 7단계. Qwen 파인튜닝 실험 재현하기

위 비교표의 마지막 줄(`Qwen HR 파인튜닝`)을 직접 만들어 보려면
[qwen-sft/](qwen-sft/) 폴더의 [README](qwen-sft/README.md) 를 따라가면 됩니다.

**이 실험은 운영에 채택하지 않았습니다.** 언어 이탈(6건→0건)과 주제 분류(33→35/35)는
해결됐지만 사실성이 17/35 에 그치고(개선 6 · 회귀 4로 상쇄) 응답이 24% 느려졌습니다.
근거는 [qwen-sft/reports/main35_ollama_comparison.md](qwen-sft/reports/main35_ollama_comparison.md).

## 7.1 전체 흐름

```text
공식 HR PDF → 사람 검수 후보 100건 → 누수·PII 검사 → 7B QLoRA SFT
           → 같은 장비에서 Base/SFT 비교 → 블라인드 근거 검수
           → 통과 시에만 GGUF 변환 후 Ollama 평가
```

## 7.2 필요한 것

| 항목 | 값 |
|---|---|
| GPU | 학습은 A40 48GB 이상 권장 (RunPod). 추론만 하려면 8GB 로도 가능 |
| 모델 | `Qwen/Qwen2.5-7B-Instruct` (commit 고정) |
| 방식 | 4-bit NF4 QLoRA, LoRA rank 16 |
| 데이터 | 검수 승인 100건 (train 80 / valid 20) — `data/candidates.jsonl` 에 포함 |

## 7.3 학습부터 평가까지

```bash
cd qwen-sft
cp .env.example .env
python -m pip install -r requirements.txt

python check_environment.py        # GPU·CUDA·패키지 확인
python -m pytest -q                # 데이터 무결성 검사
python prepare_dataset.py          # candidates.jsonl → train/valid 분할
python train_qlora.py              # QLoRA 학습 → outputs/

python evaluate.py --variant base  # 기준선
python evaluate.py --variant sft    # 학습 모델
python evaluate_topic.py --variant base
python evaluate_topic.py --variant sft
python compare_results.py          # → reports/comparison.md
```

## 7.4 이 저장소의 벤치로 재검증

학습이 끝나 Ollama 에 올렸다면, **본 서비스의 35문항 벤치**로 다시 잴 수 있습니다.
`qwen-sft/` 자체 평가와 달리 실제 서비스 경로(`generate_answer`)를 그대로 탑니다.

```bash
cd ..
python bench/run_bench.py --provider qwen --model qwen2.5-hr-sft:bench \
    --retrieval corpus --tag main35-sft-qwen
python bench/report.py
```

## 7.5 폴더에 없는 것

용량이 커서 git 에 올리지 않았습니다. 위 절차로 다시 만들 수 있습니다.

| 항목 | 크기 | 다시 만드는 법 |
|---|---|---|
| `outputs/` LoRA 어댑터 | 170MB | `train_qlora.py` |
| `tools/llama.cpp` | 201MB | `git clone` |
| `venv_convert/` | 168MB | `requirements.txt` |
| `ollama/*.gguf` | 78MB | llama.cpp 변환 (`ollama/build_manifest.json` 에 절차 기록) |
| `data/holdout.jsonl`, `corpus_cache.json` | 1.5MB | `export_holdout.py` |

## 7.6 채택 기준

실험 README 에 적어둔 게이트입니다. **사실성에서 통과하지 못했습니다.**

- 한국어 외 문장 혼입 0건 ✅ (6건 → 0건)
- 빈 답변·생성 오류 0건 ✅
- 문서에 없는 숫자·조문·절차 생성 0건 ❌ **(사실성 17/35)**
- 주제 분류가 기준선 아래로 하락하지 않음 ✅ (33 → 35/35)
- Ollama 동일 하드웨어에서 p95 5초 이하 ❌ **(17.3초)**

# 8단계. 운영 시 주의사항

- **API 키를 커밋하지 않습니다.** `.env` 는 `.gitignore` 에 있습니다
- **RAG 가 주는 `metadata.source` 는 절대경로**라 그대로 화면에 뿌리면 담당자 PC
  경로가 노출됩니다. 파일명만 잘라 씁니다
- **계측값은 API 응답에 넣지 않습니다.** 지연·토큰·모델명은 로그로만 남깁니다
- **근거 없이 답하지 않습니다.** 관련 문서가 없으면 "규정에서 찾을 수 없습니다" 로
  안내하고, RAG 장애일 때는 "잠시 후 다시 시도" 로 **구분해서** 답합니다
- 로그에 개인정보를 그대로 저장하지 않습니다
- 모델 버전·프롬프트 버전·평가 결과를 함께 보관합니다 (`bench/variants.py`)
- Gemini 무료 티어는 **하루 20회** 제한이라 전체 측정이 불가능합니다.
  한도가 모델별로 잡히므로 여유 있는 모델로 바꿔 재야 합니다

# 9단계. 검증 완료 항목

| 항목 | 결과 |
|---|---|
| 엔드포인트 4개 OpenAPI 등록 | ✅ |
| `/v1/chat` 응답이 계약대로 4개 필드 | ✅ |
| 계측값이 응답에 없고 로그에만 기록 | ✅ |
| `/v1/chat/stream` 이벤트 순서 `sources → token×N → done` | ✅ |
| 패러프레이즈 7묶음이 모두 하나의 카테고리로 수렴 | ✅ |
| 정규화 캐시 적중 (`"연차 며칠?"` == `"  연차 며칠???  "`) | ✅ |
| RAG 다운 → `200 rag_degraded=true` + 장애 안내 문구 | ✅ |
| 타임아웃 → `504 LLM_TIMEOUT` + 한국어 메시지 | ✅ |
| 키 미설정 → `503 PROVIDER_NOT_CONFIGURED` | ✅ |
| Ollama 없이 기동 → `/health` 가 `qwen: false` | ✅ |
| 실제 RAG 연동 end-to-end 35문항 | ✅ 에러 0건 |
