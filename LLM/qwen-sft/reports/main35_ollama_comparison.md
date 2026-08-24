# Qwen HR SFT v1 — 현재 `main` 서비스 경로 비교

생성일: 2026-08-03  
판정: **Ollama 연결과 추가 실험은 성공했지만, SFT v1을 답변 모델로 운영 승격하지 않는다.**

## 1. 직접 비교 결과

아래 두 실행만 동일 질문·프롬프트·코퍼스·서비스 코드·장비·Ollama 양자화 조건의 직접 비교다.

| 지표 | 현재 Base `qwen2.5:7b` | HR SFT v1 `qwen2.5-hr-sft:bench` | SFT 변화 |
|---|---:|---:|---:|
| 문항 | 35 | 35 | 동일 |
| 주제 정확도 | 33/35 (94.3%) | **35/35 (100%)** | **+2문항, +5.7%p** |
| 패러프레이즈 일관성 | 7/7 | 7/7 | 동일 |
| 중국어 이탈 | 6/35 | **0/35** | **-6건** |
| 일본어 / 영어 문장 이탈 | 0 / 0 | 0 / 0 | 동일 |
| 오류 | 0 | 0 | 동일 |
| 엄격 사실성 | 15/35 (42.9%) | 17/35 (48.6%) | +2문항, +5.7%p |
| p50 | 9.713초 | 12.518초 | **+2.805초 (+28.9%)** |
| p95 | 14.290초 | 17.487초 | **+3.197초 (+22.4%)** |
| 평균 | 9.504초 | 11.824초 | **+2.320초 (+24.4%)** |
| 최대 | 20.680초 | 18.414초 | -2.266초 |
| 전체 35문항 합계 | 332.645초 | 413.835초 | **+81.190초 (+24.4%)** |
| 5초 초과 | 31/35 | 31/35 | 동일 |
| 15초 초과 | 1/35 | **9/35** | +8건 |
| 답변 길이 중앙값 | 331자 | 369자 | +38자 (+11.5%) |
| 잘못된 조문 인용 행 | 0 | 0 | 동일 |
| 라벨 문서 회수 | 33/33 | 33/33 | 동일* |

\* `retrieval=corpus`는 문항에 라벨된 문서를 직접 제공하는 상한선 실험이므로 실제 RAG 검색 성능으로 보고하면 안 된다.

주제 분류에서 SFT가 수정한 문항은 다음 두 개다.

- `work-duty-general`: Base `복무/징계` → SFT `근태/근무형태`
- `hire-special-position`: Base `인사/승진` → SFT `채용/임용`

Base의 중국어 이탈 6건은 법령명 한자 병기가 아니라 실제 중국어 문장 출력이었다.

- `leave-parental-a`
- `leave-parental-b`
- `leave-parental-with-maternity`
- `disc-code-of-conduct`
- `other-public-institution`
- `oos-personal-balance`

SFT 35답변에는 중국어·일본어·영어 문장, 빈 답변, 중간 잘림, 반복 생성 loop, 프롬프트 형식 누출이 없었다. `leave-annual-c`의 `주(週)` 한 글자는 정상적인 법령식 한자 병기다. 다만 `총 휩가 일수`, `전형방법:와에 따른`, `그 밖에부터까지에 준하는`처럼 문장 성분이나 참조 번호가 빠진 한국어 품질 문제는 남았다.

## 2. 사실성 교차검수

기존 평가와 같은 엄격 기준을 적용했다. 명시적인 수치·조건·절차 오류가 하나라도 있거나 핵심 근거를 빠뜨린 답변은 0점으로 수동 판정했다. 자동 fact scorer 점수가 아니다.

| 사실성 전이 | 문항 수 |
|---|---:|
| Base와 SFT 모두 통과 | 11 |
| Base 실패 → SFT 통과 | 6 |
| Base 통과 → SFT 실패 | **4** |
| Base와 SFT 모두 실패 | 14 |

SFT가 엄격 기준으로 개선한 6문항은 다음과 같다.

- `leave-annual-c`: 3년마다 가산한다는 Base 오류를 2년마다 1일·25일 한도로 수정
- `hire-contract-b`: 2년 초과 시 기간제 유지라는 Base 오류를 무기계약 간주·예외로 수정
- `hire-special-position`: 특정 직위의 5년 규칙을 전체 특수직에 일반화한 오류 수정
- `promo-exam-a`: 정기시험 예외와 추가시험 조건의 혼동 수정
- `promo-hr-rule`: 경력평정 기간 구간 오류 수정
- `disc-dui-a`: 1개월 신고 주체를 인사부서가 아닌 직원의 자진신고로 수정

반대로 SFT가 새로 회귀한 4문항은 다음과 같다.

- `leave-suspension`: 모든 해외출국에 사전신고가 필요하다고 단정해 5일 이하·영유아 동반 육아휴직자 예외 누락
- `work-flexible-b`: 시차출퇴근 답변에 재택근무 전용 보안서약·교육을 섞고 신청 조건 왜곡
- `hire-contract-a`: 일반 계약 1년 미만·대체인력 2년 미만 근거와 달리 `보통 1년 단위`라고 답함
- `hire-professor`: 조교의 1년 계약을 조교수 계약기간 1년으로 오독

또한 아래 중대한 사실 오류는 SFT에서도 해결되지 않았다.

1. `leave-parental-a`
   - 문맥의 교내 직원인사규정은 자녀 1명당 육아휴직을 **3년 이내**로 정한다.
   - SFT는 일반 법률의 1년+추가 6개월만 답해 더 유리한 사내 규정을 누락했다.
2. `leave-parental-with-maternity`
   - 문맥에는 시행규칙 제14조의2의 출산전후휴가·육아휴직 **통합 신청서** 규정이 들어 있다.
   - SFT는 명확한 답변이 어렵고 동시에 신청할 수 없을 수 있다고 답해 검색된 근거와 충돌했다.
3. `pay-holiday-work`
   - 문맥의 50%와 100%는 휴일근로에 대한 **가산분**이다.
   - Base와 SFT 모두 이를 총 지급률처럼 표현하여 급여 산정 답변으로는 중대한 오류다.

그 밖에도 `leave-parental-b`, `work-flexible-a`, `work-duty-general`, `pay-overtime-a/b`, `pay-severance`, `pay-public-worker`, `promo-exam-b`, `disc-crime-report`, `oos-personal-balance` 등이 엄격 기준을 통과하지 못했다.

따라서 SFT의 언어·분류 개선은 확인됐지만 엄격 사실성은 17/35(48.6%)에 불과하다. 6개 개선과 4개 회귀가 서로 상쇄되어 HR 답변의 신뢰성 개선으로 볼 수 없다.

## 3. 기존 팀 성능표와의 관계

기존 `LLM/docs/PERFORMANCE_REPORT.md`의 제공자 표는 35번째 문항이 추가되기 전의 34문항 결과다. 아래 표는 발표용 맥락 비교이며, 새 Base↔SFT 두 행 이외에는 직접 비교로 해석하면 안 된다.

| 구분 | 모델 | 주제 정확도 | p50 | p95 | 오류 | 중국어 이탈 |
|---|---|---:|---:|---:|---:|---:|
| 역사적 34문항 | Gemini 3.5 Flash Lite | 32/34 | 1.4초 | 2.2초 | 1 | 0 |
| 역사적 34문항 | OpenAI GPT-4o mini | 33/34 | 1.9초 | 2.9초 | 0 | 0 |
| 역사적 34문항 | Qwen2.5 7B | 32/34 | 7.4초 | 11.2초 | 0 | 3 |
| 현재 35문항 | Qwen2.5 7B Base | 33/35 | 9.7초 | 14.3초 | 0 | 6 |
| 현재 35문항 | Qwen2.5 7B HR SFT v1 | **35/35** | 12.5초 | 17.5초 | 0 | **0** |

과거 Qwen 3/34와 현재 Base 6/35의 차이는 한 번씩만 실행한 확률적 결과이고 프롬프트 시점도 달라, 언어 안정성이 악화됐다고 단정할 수 없다.

## 4. 현재 애플리케이션 연결 상태

- `LLM/app/providers/qwen_provider.py`의 Ollama `/api/chat` 경로와 `generate_answer()`를 사용한 벤치는 성공했다.
- 웹 앱은 요청에 `provider`를 보내지 않고 현재 `.env`의 `DEFAULT_PROVIDER=openai`를 사용하므로, 이번 작업은 **웹 기본 모델 전환이 아니라 서비스/벤치 연결 검증**이다.
- 실제 설정의 `LLM_TIMEOUT_SEC=20`에서는 SFT 35건이 모두 20초 안에 끝났지만 여유가 작다.
- 웹 클라이언트 기본 timeout 15초 기준으로는 SFT 9/35가 초과하므로 그대로 기본 모델로 바꾸면 약 26%가 timeout 위험 구간이다. 실제 RAG 검색과 첫 요청의 채팅방 이름 생성 동시 호출까지 포함하면 위험은 더 커진다.
- 현재 provider 하나가 답변과 주제 분류를 함께 담당하므로, “상용 모델 답변 + 로컬 Qwen 주제 분류” 혼합 구성을 쓰려면 provider를 분리해야 한다.

## 5. 재현 조건

| 항목 | 값 |
|---|---|
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU, 8188 MiB, driver 610.62 |
| Ollama | 0.32.5 |
| Base | `qwen2.5:7b`, Q4_K_M, digest `845dbda0...b697e` |
| SFT 태그 | `qwen2.5-hr-sft:bench`, digest `7f36ab5d...5ce8b` |
| HF Base | `Qwen/Qwen2.5-7B-Instruct@a09a3545...` |
| 변환기 | llama.cpp `f2b52a87...` |
| GGUF LoRA | F16, 80,767,808 bytes, SHA-256 `AB129A51...75D4` |
| 질문 SHA-256 | `9CCFF6C9...2D1F` |
| 프롬프트 SHA-256 | `51257CDD...A643` |
| 실행 옵션 | `provider=qwen`, `variant=baseline`, `retrieval=corpus`, `top_k=5`, `timeout=90` |

Base 실행 뒤 SFT 실행 전에 `LLM/README.md`만 바꾸는 commit이 추가됐고 벤치 핵심 파일은 달라지지 않았다. Base commit은 `d0173d0`, SFT commit은 `df8c80c`다.

Ollama는 Qwen PEFT Safetensors 어댑터를 직접 가져오지 못해 llama.cpp로 GGUF LoRA를 만든 뒤 `FROM qwen2.5:7b`에 적용했다. 자세한 provenance는 `ollama/build_manifest.json`에 기록했다.

## 6. 판정과 다음 단계

### 지금 판정

- **답변 생성:** 승격 보류. 사실 오류와 지연 회귀 때문에 OpenAI/Gemini 발표 기준선을 대체하지 않는다.
- **한국어 제어:** 성공. 이번 35문항에서는 중국어 이탈을 6건에서 0건으로 줄였다.
- **주제 분류:** 35/35로 개선됐지만 7B 생성 모델을 분류 전용으로 쓰기에는 느리다.
- **보고서 활용:** “파인튜닝으로 언어·분류는 개선됐지만 사실성과 지연의 trade-off로 운영 채택하지 않은 실험”으로 쓰는 것이 정확하다.

### 다음 실험

1. 사실 오류 3개 이상을 우선 학습·평가 데이터에 회귀 케이스로 추가한다.
2. 같은 35문항을 Base/SFT 각각 3회 반복해 언어 이탈과 지연의 분산을 확인한다.
3. 답변 provider와 topic provider를 분리하고, topic은 임베딩/경량 분류기를 우선 검토한다.
4. 사실성 게이트를 통과한 뒤에만 `retrieval=rag` 실제 RAG E2E를 실행한다.
5. 반복 실행과 재학습은 RunPod A40에서 수행하되 최종 서비스 지연은 로컬 배포 장비에서 다시 측정한다.

## 7. 결과 파일

- Base: `LLM/bench/results/20260803-185419_main35-base-qwen_qwen.jsonl`
- SFT: `LLM/bench/results/20260803-190112_main35-sft-qwen_qwen.jsonl`
- 자동 지표: `reports/main35_ollama_metrics.json`
- 35문항 사실성 전수표: `reports/main35_fact_review.md`
- 변환 manifest: `ollama/build_manifest.json`
- Ollama Modelfile: `ollama/Modelfile`
