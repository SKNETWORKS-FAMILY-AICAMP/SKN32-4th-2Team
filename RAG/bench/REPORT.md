# RAG 성능 비교 보고서

상태: **초안 — 현재 통제 비교 실험 진행 전**

이 보고서는 세 시점의 기록을 한곳에서 추적하기 위한 문서다.

1. 실험용 변경 전 upstream `f685d76`
2. `D:/Dev_Tools/rag_test`에서 수행한 26문서 FAISS/Qdrant 실험
3. 현재 `rag-runtime`의 93문서 FAISS 및 앞으로 수행할 CPU/GPU·Qdrant 비교

과거 실험과 현재 실험은 문서 수, 질문 세트, 실행 환경, 집계 방식이 다르다. 따라서
두 시점의 절대 지연이나 품질 수치로 직접 증감률을 계산하지 않는다. 현재 백엔드와
장치의 우열은 아래의 통제 비교가 모두 끝난 뒤에 판단한다.

## 1. 목적

- 기존 수정 전 상태, FAISS 최적화, Qdrant 실험의 근거와 한계를 보존한다.
- 실제 PDF가 93개로 증가한 현재 코퍼스에서 FAISS와 Qdrant를 다시 측정한다.
- 같은 코드·인덱스·질문·검색 설정에서 CPU와 GPU의 차이를 측정한다.
- 지연만 줄고 검색 품질이 나빠지는 변경을 피하기 위해 지연과 source hit를 함께 본다.

## 2. 비교 방법

### 2.1 과거 26문서 실험

과거 지연 스냅샷은 2026-08-19 기준 26문서, 1,414청크, CUDA 환경에서
측정됐다. 고정 질의 12개를 한 번 워밍업한 뒤 질의마다 3회 호출했고, 각 질의의
중앙값 12개를 대상으로 min/p50/max/mean을 집계했다. 확장 실험은 실제 신규
문서가 아니라 기존 26개 스토어와 포인트를 반복해 26~832문서 규모를 모사했다.

답변 품질 표는 35문항, `gpt-4o-mini`, live RAG로 실행한 기존 수기 요약이다.
완전한 raw 실행 결과가 남아 있지 않은 항목은 수기 판정으로 명시한다.

### 2.2 현재 93문서 실험

현재 기준선은 LLM 호출을 제외하고 FastAPI `/api/search`만 측정한다. 질문과 정답
문서 라벨은 `LLM/bench/questions.yaml`을 사용한다. 범위 안 32문항에 대해 정답
문서가 top-k에 포함되는지와 MRR을 계산하고, 전체 35문항을 각각 3회 호출해 지연을
집계한다.

통제 비교에서는 다음 조건을 고정한다.

- 동일 Git 커밋과 동일 93문서 코퍼스
- 동일 질문 파일 SHA-256, top-k, 초기 후보 수, 워밍업 횟수, 반복 횟수
- FAISS↔Qdrant 비교 시 동일 임베딩 벡터와 동일 후처리·리랭커
- CPU↔GPU 비교 시 검색 백엔드를 고정하고 모델 장치만 변경
- warm 지연, 서버 startup-to-ready, no-warm 첫 요청을 서로 다른 지표로 기록

## 3. 실험용 변경 전 기준

upstream 커밋 `f685d76`은 변경 전 버전으로 식별됐지만, 이 커밋에서 생성한 지연
또는 품질 측정 산출물은 없다. 따라서 **원본 upstream의 측정값은 없음**이 정확한
기록이며, 이후 baseline `c0fb7f7`의 수치를 원본 측정값으로 대체하지 않는다.

## 4. 과거 26문서 결과

### 4.1 버전과 검색 지연

| 버전 | 커밋 | min (ms) | p50 (ms) | max (ms) | mean (ms) |
|---|---:|---:|---:|---:|---:|
| baseline: 스토어마다 질문 재임베딩 | `c0fb7f7` | 725.7 | 935.8 | 1,378.3 | 969.4 |
| opt1: 질문 임베딩 1회 | `f9d2a0a` | 363.7 | 407.6 | 1,088.9 | 514.5 |
| Qdrant naive (embedded) | `bfa6204` | 307.8 | 359.2 | 401.2 | 360.8 |
| Qdrant tuned (문서당 상한) | `117fbb7` | 324.5 | 360.6 | 1,027.9 | 461.9 |

opt1.5 `e2aecd6`은 opt1에 FAISS 메모리 캐시와 mtime 무효화를 추가한 버전이다.
이 버전에는 같은 12질의 retrieval snapshot이 없으므로 위 표의 min/p50/max/mean
행을 만들 수 없다.

원본 retrieval JSON을 다시 계산하면 opt1은 baseline과 top-5의 내용과 순서가
60/60 완전 동일했다. Qdrant naive는 top-1 문서 ID 10/12, 정확 청크 top-1 8/12,
동일 순위 일치 23/60, 순서 무시 top-5 겹침 38/60이었다. tuned는 정확 청크
top-1 12/12와 top-5 내용·순서 60/60으로 완전 동일했다.

기존 `RESULTS.md`에는 naive가 top1 9/12·겹침 38%, tuned가 top1 12/12·겹침
63%로 적혀 있어 원본 JSON 재계산과 다르다. 이는 top1과 overlap의 정의가 섞였거나
중간 결과가 수기 보고서에 남은 것으로 보이며, 이 보고서는 원본 JSON 재계산값을
주 결과로 사용한다.

### 4.2 답변 품질 수기 요약

| 지표 | baseline | Qdrant naive | Qdrant tuned |
|---|---:|---:|---:|
| 주제 분류 정확도 | 94.3% | 94.3% | 94.3% |
| 그룹 일관성 | 7/8 | 7/8 | 7/8 |
| 검색 recall | 87.5% | 84.4% | 87.5% |
| 조문 인용 / 오인용 | 11 / 0 | 11 / 0 | 11 / 0 |
| 범위 밖 처리 | 3/3 | 3/3 | 3/3 |
| 에러 | 0 | 0 | 0 |

opt1 답변 bench는 다시 실행하지 않았다. 기존 보고서는 검색 결과가 baseline과
12/12 동일하다는 사실을 근거로 답변 품질도 동일하다고 판단했다. 이는 별도 측정값이
아닌 기존 보고서의 추론이다.

### 4.3 문서 수 확장 시뮬레이션

| 모사 문서 수 | FAISS 매 요청 로드 (ms) | FAISS 캐시 (ms) | Qdrant embedded (ms) |
|---:|---:|---:|---:|
| 26 | 405 | 382 | 395 |
| 104 | 430 | 358 | 448 |
| 208 | 441 | 321 | 467 |
| 416 | 851 | 323 | 567 |
| 832 | 1,468 | 516 | 717 |

이 시뮬레이션에서는 매 요청 디스크 재로딩이 큰 병목으로 나타났고 FAISS 캐시가
효과적이었다. 다만 같은 데이터를 반복한 embedded/in-memory Qdrant 비교이므로,
실제 서로 다른 PDF 93개와 독립 Qdrant 서버의 HNSW 성능을 대신하지 않는다.

### 4.4 서로 일치하지 않는 과거 기록

- opt1.5 실서버 지연은 `RESULTS.md`에 cold 1,175ms / warm 429ms로 적혀 있지만,
  `history.csv`의 `opt1.5-26docs` 행은 cold 465ms / warm 중앙값 464ms다. 실행 조건을
  복원할 정보가 부족하므로 어느 하나를 정답으로 선택하지 않는다.
- 범위 밖 처리도 `RESULTS.md`는 3/3, `baseline_bench_summary.json`의 자동 집계는
  1/3이다. 수기 판정과 자동 판정이 일치하지 않으므로 이 항목을 단독 결론 근거로
  사용하지 않는다.
- Qdrant 검색 동일성도 `RESULTS.md`의 수기 수치와 raw retrieval JSON 재계산값이
  다르다. 원본 JSON과 SHA-256이 남아 있는 재계산값을 우선한다.

과거 수치와 출처는 `RAG/bench/history/legacy_results.json`에 구조화했다. 기존
`rag_test` 파일 자체는 복사하지 않았다.

## 5. 현재 93문서 live FAISS CPU 결과

측정 커밋은 `eee905d`이며 워크트리는 측정 당시 clean 상태였다. Python 3.11.9,
`torch 2.13.0+cpu`, CUDA unavailable, 워밍업된 FAISS 스토어 93개 조건이다. 질문
35개를 각 3회 호출한 성공 표본은 105개이고 실패는 0건이었다.

측정 호스트는 Intel Core i9-13900HX(24코어/32스레드), 메모리
34,158,272,512바이트, NVIDIA GeForce RTX 4070 Laptop GPU(8,188MiB,
드라이버 610.62)다. GPU 하드웨어는 있으나 이 CPU 기준선의 PyTorch가 CPU 빌드라
CUDA를 사용하지 않았다.

| 지표 | 결과 |
|---|---:|
| 지연 min | 7,904.9ms |
| 지연 p50 | 9,046.2ms |
| 지연 p95 | 9,809.9ms |
| 지연 max | 9,946.7ms |
| 지연 mean | 9,028.0ms |
| source hit@1 | 0.5312 |
| source hit@3 | 0.8125 |
| source hit@5 | 0.9062 |
| MRR | 0.6833 |
| 실패 요청 | 0 |

Raw 결과: `RAG/bench/results/20260826_current-faiss-cpu-warm.json`

이 수치는 현재 live CPU warm 기준선이다. 과거 26문서 GPU 실험과 조건이 다르므로
과거 표와의 직접 증감률은 산출하지 않는다.

source hit@5에서 라벨상 실패한 3문항은 `work-duty-general`, `pay-overtime-a`,
`pay-holiday-work`다. 이 중 `pay-overtime-a`는 검색 결과에
`시간외근무수당지급지침.pdf`가 포함됐지만 기대 문서 목록에는 이 문서가 없다.
따라서 현재 source hit은 백엔드 간 상대 비교에는 쓸 수 있지만, 라벨을 도메인
검수하기 전에는 절대적인 정답률로 해석하지 않는다.

## 6. 현재 93문서 통제 비교

아래 표의 TODO는 측정 전 자리표시자다. 값이 채워지기 전에는 FAISS/Qdrant 또는
CPU/GPU의 최종 우열을 결론 내리지 않는다.

| 백엔드 | 장치 | startup-to-ready | no-warm first | warm p50 | warm p95 | hit@1 | hit@3 | hit@5 | MRR | 실패 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| FAISS cache | CPU | **TODO: FAISS_CPU_STARTUP** | **TODO: FAISS_CPU_COLD** | 9,046.2ms | 9,809.9ms | 0.5312 | 0.8125 | 0.9062 | 0.6833 | 0 |
| FAISS cache | GPU | **TODO: FAISS_GPU_STARTUP** | **TODO: FAISS_GPU_COLD** | **TODO: FAISS_GPU_P50** | **TODO: FAISS_GPU_P95** | **TODO: FAISS_GPU_HIT1** | **TODO: FAISS_GPU_HIT3** | **TODO: FAISS_GPU_HIT5** | **TODO: FAISS_GPU_MRR** | **TODO: FAISS_GPU_FAILURES** |
| Qdrant | CPU | **TODO: QDRANT_CPU_STARTUP** | **TODO: QDRANT_CPU_COLD** | **TODO: QDRANT_CPU_P50** | **TODO: QDRANT_CPU_P95** | **TODO: QDRANT_CPU_HIT1** | **TODO: QDRANT_CPU_HIT3** | **TODO: QDRANT_CPU_HIT5** | **TODO: QDRANT_CPU_MRR** | **TODO: QDRANT_CPU_FAILURES** |
| Qdrant | GPU | **TODO: QDRANT_GPU_STARTUP** | **TODO: QDRANT_GPU_COLD** | **TODO: QDRANT_GPU_P50** | **TODO: QDRANT_GPU_P95** | **TODO: QDRANT_GPU_HIT1** | **TODO: QDRANT_GPU_HIT3** | **TODO: QDRANT_GPU_HIT5** | **TODO: QDRANT_GPU_MRR** | **TODO: QDRANT_GPU_FAILURES** |

추가로 결정하고 기록해야 할 항목:

- **TODO: QDRANT_MODE** — 과거 embedded exact 재현과 독립 Qdrant 서버 HNSW 중
  어떤 결과를 본 비교표에 넣는지 명시
- **TODO: CONTROLLED_RUN_COMMIT** — 네 조건을 모두 실행할 고정 커밋
- **TODO: QUESTIONS_SHA256** — 네 조건이 동일 질문 파일을 사용했는지 확인
- **TODO: SEARCH_CONFIG** — top-k, 초기 후보 수, 문서당 후보 상한을 확정
- **TODO: CUDA_RUNTIME** — GPU 빌드 PyTorch, CUDA 버전, GPU 모델을 기록

## 7. 한계

- upstream `f685d76`은 측정 산출물이 없어서 숫자 비교가 불가능하다.
- 과거와 현재는 26문서/93문서, 12질의/35질의, GPU/CPU가 서로 다르다.
- 과거 확장 표는 실제 신규 문서가 아니라 기존 스토어 반복 시뮬레이션이다.
- 과거 Qdrant는 embedded in-memory exact 방식이라 운영형 Qdrant 서버 HNSW와 다르다.
- 현재 source hit는 기대 문서명의 포함 여부이며 답변의 사실성 전체를 뜻하지 않는다.
- 현재 CPU warm 측정만 완료됐고 CPU/GPU·FAISS/Qdrant 통제 비교는 미완료다.
- 현재 RAG 가상환경의 PyTorch는 CPU 빌드다. GPU 측정 전 환경 변경과 검증이 필요하며,
  환경을 변경하지 않은 상태에서 `RAG_DEVICE=cuda`만 지정해서는 GPU 비교가 되지 않는다.

## 8. 재현 명령

현재 서버가 `/health`에서 `models_ready=true`가 된 뒤 live RAG 기준선을 실행한다.

```powershell
RAG\.venv\Scripts\python.exe RAG\bench\run_api_bench.py `
  --label current-faiss-cpu-warm --repeats 3
```

벤치마크 집계 로직 회귀 테스트:

```powershell
RAG\.venv\Scripts\python.exe -m unittest RAG.bench.test_run_api_bench
```

GPU와 Qdrant 재현 명령은 구현 및 환경 확정 후 아래 자리에 추가한다.

```text
TODO: FAISS_GPU_REPRO_COMMAND
TODO: QDRANT_CPU_REPRO_COMMAND
TODO: QDRANT_GPU_REPRO_COMMAND
TODO: STARTUP_AND_NO_WARM_REPRO_COMMANDS
```

과거 실험의 원본 산출물은 `D:/Dev_Tools/rag_test/eval`에 보존한다. 기존 폴더는
재현 실행 소스로 수정하지 않고 현재 저장소의 벤치 도구로 새 결과를 생성한다.

## 9. 결론

과거 26문서 실험에서는 질문 임베딩 1회와 FAISS 캐시가 병목을 줄였고, 당시
Qdrant naive는 검색 결과 겹침과 recall이 낮아 tuned 보정이 필요했다. 현재 93문서
live CPU warm 기준선은 확보했다.

**최종 결론은 보류한다.** 동일 93문서·동일 질문·동일 설정에서 FAISS/Qdrant와
CPU/GPU의 통제 비교, startup/no-warm 측정이 끝난 뒤 백엔드와 운영 장치를 결정한다.
