# RAG 성능 비교 최종 보고서

> 이 문서는 검색 파이프라인 상세 보고서다. 현재 93 PDF의 실제 RAG + LLM
> 답변 품질까지 포함한 통합 결론은
> `산출물/[필수] 시스템 아키텍처, 테스트 계획 및 결과 보고서/RAG_LLM_PERFORMANCE_REPORT_20260826.md`
> 에 정리했다.

상태: **완료**

측정일: **2026-08-26**

주 결과 기준: `RAG/bench/results/20260826_controlled-summary.json`

이 보고서는 실험 전 upstream, `D:/Dev_Tools/rag_test`의 과거 26 PDF 실험,
현재 `rag-runtime`의 93 PDF 실험을 한 문서에 정리한다. 과거와 현재는 코퍼스,
질문 수, 코드 및 측정 경로가 다르므로 서로의 절대 지연을 직접 비교하지 않는다.
현재 의사결정은 동일 조건으로 다시 실행한 8개 통제 실험을 기준으로 한다.

## 1. 결론 및 권장 구성

현재 93 PDF·3,681 청크 규모의 권장 구성은 **문서별 캐시 FAISS + CUDA
CrossEncoder FP16 + 초기 후보 20개 + 최종 top-k 5**다.

- FAISS 후보 20의 통제 실험에서 CUDA p50은 **177.524ms**, CPU p50은
  **5,222.854ms**로 CUDA 실행 모드가 **29.42배** 빨랐다.
- 같은 후보 20에서 tuned Qdrant와 FAISS의 최종 top-5 순서는 35/35 문항에서
  완전히 같았다. 그러나 벡터 검색 p50은 CUDA 기준 FAISS **3.392ms**, Qdrant
  **17.450ms**였고, 전체 p50도 FAISS **177.524ms**, Qdrant **191.860ms**였다.
  현재 규모에서는 Qdrant로 바꿀 성능상 근거가 확인되지 않았다.
- 후보 10은 FAISS CUDA p50을 **97.318ms**까지 낮췄지만, 후보 20과 완전히 같은
  순위는 7/35뿐이었다. top-5 원소 집합까지 같은 문항도 12/35였고 전체 top-5
  원소 겹침은 80%였다. hit@5는 29/32에서 30/32로 늘었지만 hit@1은 17/32에서
  16/32로, MRR은 0.683333에서 0.674479로 낮아졌다.
- 따라서 후보 10은 **저지연 실험 옵션**으로 보존하되, 기대 문서 라벨을 도메인
  검수하고 실제 답변 품질까지 확인하기 전에는 기본값 20을 유지한다.

CPU와 CUDA 수치는 장치만 바꾼 동일 정밀도 비교가 아니다. 현재 코드는 CPU
CrossEncoder를 기본 FP32로, CUDA CrossEncoder를 FP16으로 적재한다. 따라서 이
보고서의 CPU/GPU 배율은 **CPU FP32 대비 CUDA FP16의 실제 배포 모드 차이**이며,
순수 하드웨어만의 가속 배율로 해석하지 않는다.

## 2. 비교 범위와 측정 방법

### 2.1 비교한 세 시점

1. 실험용 변경 전 upstream `f685d76`: 커밋만 식별되며 측정 산출물은 없다.
2. 과거 `rag_test`: 26 PDF, 1,414 청크, 2026-08-19 CUDA 실험이다.
3. 현재 `rag-runtime`: 실제 93 PDF, 3,681 청크를 사용한 2026-08-26 실험이다.

과거 26 PDF 결과는 이력 보존과 변경 방향 확인에만 사용한다. 현재 백엔드·장치·후보
수 선택은 93 PDF 통제 행렬 안에서만 비교한다.

### 2.2 현재 통제 실험

- 질문: `LLM/bench/questions.yaml`의 35문항
- 질문 SHA-256:
  `fa0355bfa69cf173acf03e70380b82e3a6d653b3a327ceaced6fcab372cbff53`
- 실행: 조건마다 새 Python 프로세스, 워밍업 1회, 문항당 3회, 총 105회
- 순서: round-major로 35문항을 한 번씩 순회한 뒤 다음 반복 수행
- 검색: 최종 top-k 5, 문서당 최대 3청크, Qdrant 선조회 80개
- 후보 비교: CrossEncoder/BM25 입력만 20개와 10개로 변경
- 모델: `jhgan/ko-sroberta-multitask`, `BAAI/bge-reranker-v2-m3`
- 벡터: 기존 FAISS 벡터를 그대로 사용하며 코퍼스를 다시 임베딩하지 않음
- 범위: HTTP와 LLM 호출을 제외한 직접 검색 파이프라인
- 타이밍: CUDA 실행 전후를 동기화하고 embed, vector search, BM25, rerank,
  finalize를 각각 기록
- 코드: `e17217c1592a32eaacb1fc183cd69c2c25585319`, 모든 8개 행 측정 시
  `git_dirty=false`

`qdrant-tuned`는 독립 서버나 HNSW가 아니다. 동일 벡터를 로컬 embedded
in-memory **exact** Qdrant에 적재하고 80개를 조회한 뒤 문서당 3개 제한과 전체
후보 제한을 적용한 비교용 구현이다. FAISS와 Qdrant 검색 자체는 CPU에서 수행되고,
CUDA는 질문 임베딩과 CrossEncoder 리랭킹에 사용된다.

검색 품질은 범위 안 32문항에서 기대 PDF 이름이 결과에 들어오는지를 hit@1/3/5와
MRR로 계산했다. 이는 검색 source hit이지 답변 사실성이나 LLM 답변 품질 점수가
아니다.

## 3. 현재 코퍼스 및 실행 환경

| 항목 | 값 |
|---|---|
| PDF | 93개 |
| FAISS 스토어 | 93개 |
| 청크/벡터 | 3,681개 |
| 인덱스 | 768차원 `IndexFlatL2`, `METRIC_L2` |
| 청킹 | size 400, overlap 80, 최소 80, 조문 머리말 사용 |
| 기본 검색 설정 | 후보 20, top-k 5 |
| Python | 3.11.9 |
| PyTorch | 2.13.0+cu130 |
| CUDA build | 13.0 |
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU |
| 브랜치/커밋 | `rag-runtime` / `e17217c` |

코퍼스 고정 여부는 다음 해시로 확인한다.

| 대상 | SHA-256 |
|---|---|
| PDF 집합 | `ff94c6ed20a596825baa3c8bc70e4cfc13116df5bb372b7e93a85ca77abe103c` |
| FAISS 스토어 집합 | `9c6b242931c57a616771ca07afdc41c28aa00ce475f226d57b11cc7b6387c1f2` |
| PDF + 인덱스 + 질문 전체 | `88be510fd2d0c6e590cc2104ebf8ff51295f360627943bff2b9c60c7730a1722` |
| manifest 파일 | `ef090e64bb74321156fcbb3d25751023a6bc53215d3ac0e5cd9c486a12c7b43c` |

Manifest는 `2026-08-25T18:18:29.028697+00:00`에 생성됐으며 Git 상태는 clean이다.

## 4. 과거 26 PDF 실험

### 4.1 버전과 검색 지연

과거 고정 검색 실험은 12질의를 한 번 워밍업한 뒤 질의마다 3회 호출했다. 각 질의의
중앙값 12개를 대상으로 아래 통계를 냈다.

| 버전 | 커밋 | min (ms) | p50 (ms) | max (ms) | mean (ms) |
|---|---:|---:|---:|---:|---:|
| baseline: 스토어마다 질문 재임베딩 | `c0fb7f7` | 725.7 | 935.8 | 1,378.3 | 969.4 |
| opt1: 질문 임베딩 1회 | `f9d2a0a` | 363.7 | 407.6 | 1,088.9 | 514.5 |
| Qdrant naive, embedded exact | `bfa6204` | 307.8 | 359.2 | 401.2 | 360.8 |
| Qdrant tuned, embedded exact | `117fbb7` | 324.5 | 360.6 | 1,027.9 | 461.9 |

opt1.5 `e2aecd6`은 질문 임베딩 1회에 FAISS 메모리 캐시와 mtime 무효화를
추가했지만 동일 12질의 raw snapshot이 없어 위 표에 넣지 않았다.

원본 retrieval JSON 재계산 결과는 다음과 같다.

- opt1 대 baseline: 정확 top-1 청크 12/12, 동일 순위 60/60, 순서 무시 top-5
  겹침 60/60
- Qdrant naive 대 baseline: top-1 문서 ID 10/12, 정확 top-1 청크 8/12,
  동일 순위 23/60, 순서 무시 top-5 겹침 38/60
- Qdrant tuned 대 baseline: 정확 top-1 청크 12/12, 동일 순위 60/60,
  순서 무시 top-5 겹침 60/60

즉 과거에도 단순 전역 Qdrant 후보는 특정 문서의 여러 청크가 후보를 점유할 수
있었고, 문서당 상한을 둔 tuned 방식에서 FAISS 결과가 복원됐다.

### 4.2 과거 답변 품질 수기 요약

다음 값은 35문항과 `gpt-4o-mini` live RAG를 사용한 기존 `RESULTS.md`의 수기
요약이다. 완전한 raw 답변 실행 파일이 모두 남아 있지 않으므로 현재 자동 통제
결과와 같은 증거 수준으로 취급하지 않는다.

| 지표 | baseline | Qdrant naive | Qdrant tuned |
|---|---:|---:|---:|
| 주제 분류 정확도 | 94.3% | 94.3% | 94.3% |
| 그룹 일관성 | 7/8 | 7/8 | 7/8 |
| 검색 recall | 87.5% | 84.4% | 87.5% |
| 조문 인용 / 오인용 | 11 / 0 | 11 / 0 | 11 / 0 |
| 범위 밖 처리 | 3/3 | 3/3 | 3/3 |
| 에러 | 0 | 0 | 0 |

opt1 답변 bench는 재실행하지 않았고, 기존 보고서는 retrieval이 baseline과 같다는
이유로 답변 품질도 같을 것이라고 추론했다. 이는 독립 측정값이 아니다.

### 4.3 과거 문서 수 확장 시뮬레이션

| 모사 문서 수 | FAISS 매 요청 로드 (ms) | FAISS 캐시 (ms) | Qdrant embedded exact (ms) |
|---:|---:|---:|---:|
| 26 | 405 | 382 | 395 |
| 104 | 430 | 358 | 448 |
| 208 | 441 | 321 | 467 |
| 416 | 851 | 323 | 567 |
| 832 | 1,468 | 516 | 717 |

이 표는 실제 서로 다른 PDF를 늘린 결과가 아니다. 기존 26개 스토어와 포인트를
반복해 규모만 모사했으므로, 실제 93 PDF 결과나 운영형 Qdrant 성능을 대신할 수
없다. 다만 매 요청 FAISS 재로딩을 제거하고 캐시해야 한다는 방향은 확인됐다.

### 4.4 과거 기록 불일치

- 기존 `RESULTS.md`는 Qdrant naive를 top1 9/12·overlap 38%, tuned를 top1
  12/12·overlap 63%로 적었다. raw JSON 재계산은 각각 exact top-1 청크 8/12·
  top-5 38/60, exact top-1 12/12·top-5 60/60이다. 이 보고서는 raw 재계산값을
  우선한다.
- opt1.5 지연은 `RESULTS.md`에 1,175ms/429ms, `history.csv`에
  465ms/464ms로 기록돼 있다. 실행 조건을 복원할 수 없어 어느 한쪽을 정답으로
  선택하지 않는다.
- baseline 범위 밖 처리는 수기 보고서가 3/3, 자동 summary가 1/3이다. 판정 기준이
  달라 이 항목을 결론의 단독 근거로 사용하지 않는다.

과거 원본 경로와 각 SHA-256은 `RAG/bench/history/legacy_results.json`에 보존했다.
기존 `D:/Dev_Tools/rag_test` 작업 폴더는 수정하지 않았다.

## 5. 현재 live FAISS 참고 결과

다음 표는 실제 `/api/search` HTTP 경로에서 실행한 warm 기준선이다. 통제 행렬과 달리
서버, HTTP 직렬화 및 해당 시점의 프로세스 상태를 포함하므로 통제 행렬에 섞지 않는다.

| live 경로 | Torch/장치 | 커밋·상태 | 표본 | p50 (ms) | p95 (ms) | mean (ms) | 실패 |
|---|---|---|---:|---:|---:|---:|---:|
| FAISS CPU | 2.13.0+cpu / CPU | `eee905d`, clean | 105 | 9,046.2 | 9,809.9 | 9,028.0 | 0 |
| FAISS CUDA, 후보 20 | 2.13.0+cu130 / CUDA | `e17217c`, clean | 105 | 186.3 | 208.5 | 185.9 | 0 |

| live 경로 | hit@1 | hit@3 | hit@5 | MRR | 반복 순위 불안정 |
|---|---:|---:|---:|---:|---:|
| FAISS CPU | 17/32 (0.5312) | 26/32 (0.8125) | 29/32 (0.9062) | 0.6833 | 0 |
| FAISS CUDA, 후보 20 | 17/32 (0.5312) | 26/32 (0.8125) | 29/32 (0.9062) | 0.6833 | 0 |

두 실행 모두 35문항을 3회씩 성공했고 같은 질문 SHA-256과 93개 스토어를 사용했다.
GPU 실행 전 health는 `models_ready=true`, warmed store 93, warmup failure 0이었다.
서버는 `RAG_DEVICE=cuda`로 명시 실행했고 시작 로그로 CUDA 모델 적재를 확인했다.
다만 API 결과 JSON의 `runtime`은 벤치 클라이언트 프로세스 정보이므로 그것만으로
원격 서버 장치를 증명하지는 못한다. 이 로컬 실행은 서버 시작 로그가 이를 보강한다.

GPU live 측정도 clean 상태에서 수행했다. 다만 CPU와 GPU live 실행은 PyTorch
빌드와 커밋이 달라 이 둘의 비율을 주된 CPU/GPU 결론으로 사용하지 않고, 아래
동일 커밋의 clean 통제 행렬을 사용한다.

source hit@5에서 후보 20의 라벨상 실패는 `work-duty-general`, `pay-overtime-a`,
`pay-holiday-work`다. `pay-overtime-a`에는 실제 결과에
`시간외근무수당지급지침.pdf`가 포함됐지만 기대 문서 목록에는 그 파일이 없다.
따라서 source hit은 백엔드 간 상대 비교에는 유용하지만 도메인 라벨 검수 전 절대
정답률로 해석하지 않는다.

## 6. 현재 93 PDF 통제 결과

### 6.1 8개 조건 전체 행렬

아래 값은 최신 재실행 raw 파일로 다시 생성한 summary의 값이다. 모든 행은 105개
timed call을 포함하고, 행 내부 반복 순위 불안정은 0건이었다.

| 백엔드 | 실행 모드 | 후보 | p50 (ms) | p95 (ms) | mean (ms) | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| FAISS cached | CPU FP32 | 10 | 2,617.286 | 2,943.974 | 2,640.686 | 16/32 | 27/32 | 30/32 | 0.674479 |
| FAISS cached | CPU FP32 | 20 | 5,222.854 | 5,840.997 | 5,233.395 | 17/32 | 26/32 | 29/32 | 0.683333 |
| FAISS cached | CUDA FP16 | 10 | 97.318 | 110.417 | 97.437 | 16/32 | 27/32 | 30/32 | 0.674479 |
| FAISS cached | CUDA FP16 | 20 | 177.524 | 209.245 | 180.004 | 17/32 | 26/32 | 29/32 | 0.683333 |
| Qdrant tuned exact | CPU FP32 | 10 | 2,705.826 | 2,998.251 | 2,697.747 | 16/32 | 27/32 | 30/32 | 0.674479 |
| Qdrant tuned exact | CPU FP32 | 20 | 5,217.141 | 5,872.236 | 5,294.154 | 17/32 | 26/32 | 29/32 | 0.683333 |
| Qdrant tuned exact | CUDA FP16 | 10 | 105.421 | 117.312 | 106.608 | 16/32 | 27/32 | 30/32 | 0.674479 |
| Qdrant tuned exact | CUDA FP16 | 20 | 191.860 | 229.762 | 193.545 | 17/32 | 26/32 | 29/32 | 0.683333 |

CPU 대비 CUDA의 total p50 배율은 다음과 같다.

| 백엔드 | 후보 10 | 후보 20 |
|---|---:|---:|
| FAISS cached | 26.89배 | 29.42배 |
| Qdrant tuned exact | 25.67배 | 27.19배 |

### 6.2 단계별 p50

| 백엔드 | 모드 | 후보 | embed | vector | BM25 | rerank | finalize | total |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| FAISS cached | CPU | 10 | 20.712 | 6.027 | 3.425 | 2,588.316 | 0.446 | 2,617.286 |
| FAISS cached | CPU | 20 | 20.649 | 6.045 | 6.651 | 5,192.141 | 0.832 | 5,222.854 |
| FAISS cached | CUDA | 10 | 7.949 | 3.442 | 1.779 | 83.354 | 0.248 | 97.318 |
| FAISS cached | CUDA | 20 | 7.262 | 3.392 | 3.377 | 161.478 | 0.423 | 177.524 |
| Qdrant tuned exact | CPU | 10 | 20.612 | 20.232 | 3.440 | 2,644.476 | 0.443 | 2,705.826 |
| Qdrant tuned exact | CPU | 20 | 20.961 | 21.272 | 6.571 | 5,168.595 | 0.802 | 5,217.141 |
| Qdrant tuned exact | CUDA | 10 | 7.396 | 13.452 | 1.802 | 82.355 | 0.252 | 105.421 |
| Qdrant tuned exact | CUDA | 20 | 7.642 | 17.450 | 3.413 | 163.191 | 0.443 | 191.860 |

단위는 ms다. 각 열의 p50은 단계별로 독립 계산했기 때문에 열의 합이 total p50과
정확히 같을 필요는 없다. CPU에서는 리랭킹이 약 2.6초 또는 5.2초로 병목을
지배했다. CUDA FP16에서는 리랭킹 p50이 후보 20 기준 약 161~163ms로 줄었다.
반면 벡터 검색은 두 장치 모두 CPU에서 실행되며, 현 코퍼스에서 tuned Qdrant의
벡터 단계는 FAISS보다 일관되게 길었다.

### 6.3 후보 20 대 10

| 백엔드 | 모드 | p50 20→10 (ms) | 감소율 | 완전 동일 순위 | 동일 top-5 집합 | 원소 겹침 |
|---|---|---:|---:|---:|---:|---:|
| FAISS cached | CPU | 5,222.854 → 2,617.286 | 49.89% | 7/35 | 12/35 | 140/175 (80%) |
| FAISS cached | CUDA | 177.524 → 97.318 | 45.18% | 7/35 | 12/35 | 140/175 (80%) |
| Qdrant tuned exact | CPU | 5,217.141 → 2,705.826 | 48.14% | 7/35 | 12/35 | 140/175 (80%) |
| Qdrant tuned exact | CUDA | 191.860 → 105.421 | 45.05% | 7/35 | 12/35 | 140/175 (80%) |

후보 수 변경의 검색 결과 차이는 백엔드와 장치에 관계없이 같았다. 35문항 중
28문항에서 최종 순서가 하나 이상 달라졌고, 6문항은 top-1 청크도 달라졌다.

| 품질 지표 | 후보 20 | 후보 10 | 변화 |
|---|---:|---:|---:|
| hit@1 | 17/32 (53.125%) | 16/32 (50.000%) | -1문항 |
| hit@3 | 26/32 (81.250%) | 27/32 (84.375%) | +1문항 |
| hit@5 | 29/32 (90.625%) | 30/32 (93.750%) | +1문항 |
| MRR | 0.683333 | 0.674479 | -0.008854 |

후보 10이 hit@5를 한 건 늘렸지만 top-1과 MRR은 낮아졌고 top-5 구성도 20%가
바뀌었다. 32개의 기대 문서 라벨만으로 어느 쪽이 실질 답변 품질이 더 좋다고
단정할 수 없다. 그래서 지연 절반이라는 이득은 명확하지만, 기본값 변경은 보류한다.

CPU와 CUDA의 후보 20 결과는 각 백엔드에서 35/35 완전 동일했다. 후보 10은
top-5 집합과 top-1은 35/35 같았으나 `pay-severance`의 내부 순서만 달라져 정확
순서 일치는 34/35였다. 이는 FP32와 FP16의 근소한 점수 차이 가능성을 보여준다.

### 6.4 FAISS 대 tuned Qdrant

| 장치 | 후보 | 완전 동일 최종 순위 | 동일 top-5 집합 | 원소 겹침 |
|---|---:|---:|---:|---:|
| CPU | 10 | 35/35 | 35/35 | 100% |
| CPU | 20 | 35/35 | 35/35 | 100% |
| CUDA | 10 | 35/35 | 35/35 | 100% |
| CUDA | 20 | 35/35 | 35/35 | 100% |

tuned Qdrant는 검색 결과 동일성을 달성했지만 현재 3,681벡터에서는 지연 이점이
없었다. 예를 들어 CUDA 후보 20에서 전체 p50은 FAISS보다 14.336ms 길었고,
벡터 단계 자체는 14.058ms 길었다. Qdrant의 운영 기능이 필요하거나 벡터 규모가
크게 증가할 때 독립 서버 구성을 별도 설계해 다시 측정할 수 있지만, 이 exact
실험으로 그런 구성의 성능을 예측할 수는 없다.

### 6.5 Qdrant naive 보충 실험

Qdrant naive는 주 8개 행렬 밖에서 CUDA·후보 20으로 clean 상태(`e17217c`)에서
35문항×3회를 실행했다.

| p50 | p95 | hit@1 | hit@3 | hit@5 | MRR |
|---:|---:|---:|---:|---:|---:|
| 184.629ms | 205.221ms | 18/32 | 27/32 | 29/32 | 0.701562 |

naive 후보의 문서 다양성은 평균 7.6571개 문서였고 한 문서가 최대 15/20청크를
차지했다. tuned는 평균 11.1429개 문서, 문서당 최대 3청크였다. naive와 tuned의
최종 순서가 완전히 같은 문항은 6/35, top-5 원소 겹침은 121/175(69.14%)였다.

naive의 제한된 source hit 수치가 일부 높더라도 더 좋은 검색이라고 결론 내리지
않는다. 라벨 수가 적고 일부 기대 문서 라벨에 결함이 있으며, 한 문서의 중복 청크가
후보를 과점하는 현상이 확인됐기 때문이다. 이 결과는 문서 다양성 제한의 필요성을
확인하는 보충 자료로만 사용한다.

## 7. 최종 판단

1. **장치:** CUDA FP16을 사용한다. 현재 가장 큰 병목인 CrossEncoder 리랭킹을
   CPU 대비 약 26~29배 빠르게 줄였다.
2. **백엔드:** 현재 규모에서는 캐시된 문서별 FAISS를 유지한다. tuned Qdrant와
   최종 결과가 완전히 같고 FAISS의 벡터 단계가 더 짧으며, 별도 백엔드 운영을
   추가할 성능상 이득이 없다.
3. **후보 수:** 운영 기본값은 20을 유지한다. 후보 10은 약 45~50% 더 빠르지만
   순위 변화가 크고 top-1/MRR이 소폭 하락했다.
4. **후속 검증:** 후보 10을 적용하려면 기대 문서 라벨을 먼저 고치고, 현재
   검색 결과를 이용한 실제 LLM 답변의 사실성·인용·거절 품질을 별도 평가한다.
5. **Qdrant 재검토 조건:** 벡터가 크게 증가하거나 필터링·분산·영속 서비스 등
   운영 요구가 생겼을 때, 독립 서버 구성을 별도의 실험 계획으로 평가한다.

## 8. 한계

- upstream `f685d76`에는 측정 산출물이 없어 수정 전 절대 수치가 없다.
- 과거와 현재 결과는 26/93 PDF, 12/35질의 및 코드가 달라 직접 증감률을 계산할
  수 없다.
- 통제 행렬은 직접 backend warm 검색이며 HTTP, Django, LLM 호출을 포함하지 않는다.
- live CPU/GPU 결과는 별도 참고값이다. 서로 다른 PyTorch 빌드·커밋·프로세스
  상태이므로 clean 통제 행렬과 같은 수준의 인과 비교가 아니다.
- CPU는 FP32, CUDA CrossEncoder는 FP16이므로 CPU/GPU 배율에 정밀도 변화도
  포함된다.
- 현재 Qdrant는 로컬 embedded in-memory exact 비교뿐이다. 독립 Qdrant 서버나
  HNSW의 성능을 측정하지 않았다.
- 순차 단일 요청만 측정했다. 동시 부하에서의 처리량과 지연 분포는 측정하지 않았다.
- warm 요청만 비교했다. 서버 시작 시간과 캐시 없는 첫 요청은 측정하지 않았다.
- 프로세스 RSS는 raw에 남아 있지만 GPU VRAM 사용량은 측정하지 않았다.
- 현재 자동 평가는 기대 PDF 포함 여부만 본다. LLM 답변 품질과 사실성은 측정하지
  않았다.
- 35문항과 단일 PC·단일 측정일 결과이므로 더 큰 질의 세트와 반복 일자 검증이
  필요하다.

## 9. 재현 방법

새 가상환경을 만들지 않고 저장소의 `RAG/.venv`를 사용한다.

### 9.1 환경 및 manifest 확인

```powershell
RAG\.venv\Scripts\python.exe -m pip check
RAG\.venv\Scripts\python.exe RAG\bench\capture_manifest.py `
  --output "$env:TEMP\rag-corpus-manifest.json"
```

생성한 manifest의 PDF·스토어·질문 해시가 3절과 같을 때만 같은 코퍼스 비교로
취급한다.

### 9.2 직접 backend 통제 행렬

다음 명령은 2개 백엔드×2개 장치×2개 후보 수를 각각 새 프로세스에서 실행한다.
기본 timestamp 파일명을 사용하므로 보존된 결과를 덮어쓰지 않는다.

```powershell
foreach ($backend in @('faiss-cached', 'qdrant-tuned')) {
  foreach ($device in @('cpu', 'cuda')) {
    foreach ($candidates in @(10, 20)) {
      RAG\.venv\Scripts\python.exe RAG\bench\run_backend_bench.py `
        --backend $backend --device $device `
        --initial-candidates $candidates --qdrant-fetch 80 `
        --warmups 1 --repeats 3 `
        --label "repro-c$candidates"
    }
  }
}
```

Qdrant naive 보충 실험:

```powershell
RAG\.venv\Scripts\python.exe RAG\bench\run_backend_bench.py `
  --backend qdrant-naive --device cuda `
  --initial-candidates 20 --warmups 1 --repeats 3 `
  --label repro-naive-c20
```

보존된 8개 raw 파일로 summary 로직을 다시 검증할 때는 결과를 임시 파일에 쓴다.

```powershell
RAG\.venv\Scripts\python.exe RAG\bench\summarize_backend_results.py `
  RAG\bench\results\20260826_controlled-faiss-cached-cpu-c10.json `
  RAG\bench\results\20260826_controlled-faiss-cached-cpu.json `
  RAG\bench\results\20260826_controlled-faiss-cached-gpu-c10.json `
  RAG\bench\results\20260826_controlled-faiss-cached-gpu-c20.json `
  RAG\bench\results\20260826_controlled-qdrant-tuned-cpu-c10.json `
  RAG\bench\results\20260826_controlled-qdrant-tuned-cpu.json `
  RAG\bench\results\20260826_controlled-qdrant-tuned-gpu-c10.json `
  RAG\bench\results\20260826_controlled-qdrant-tuned-gpu-c20.json `
  --manifest RAG\bench\results\20260826_corpus-manifest.json `
  --supplemental RAG\bench\results\20260826_controlled-qdrant-naive-gpu-c20.json `
  --json-output "$env:TEMP\rag-controlled-summary.json" `
  --csv-output "$env:TEMP\rag-controlled-summary.csv"
```

### 9.3 live API 참고 측정

서버를 후보 20과 명시 장치로 실행한 뒤 `/health`에서 `models_ready=true`, warmed
store 93, failure 0을 확인한다. 다음 환경 변수는 서버 프로세스에 적용해야 한다.

```powershell
$env:RAG_DEVICE = 'cuda'
$env:RAG_SEARCH_INITIAL_CANDIDATES = '20'
$env:RAG_SEARCH_TOP_K = '5'
RAG\.venv\Scripts\python.exe RAG\app.py
```

다른 터미널에서 실행한다.

```powershell
RAG\.venv\Scripts\python.exe RAG\bench\run_api_bench.py `
  --label repro-faiss-gpu-warm-c20 --warmups 1 --repeats 3
```

### 9.4 회귀 테스트

```powershell
RAG\.venv\Scripts\python.exe -m unittest `
  RAG.bench.test_capture_manifest `
  RAG.bench.test_run_api_bench `
  RAG.bench.test_run_backend_bench `
  RAG.bench.test_summarize_backend_results
```

## 10. 결과 산출물 색인

| 산출물 | 역할 | SHA-256 |
|---|---|---|
| `RAG/bench/history/legacy_results.json` | 과거 결과·출처·불일치 기록 | `82b75c4f9536b226e7db137d956c16f15b45afd555be87d16025ef0895a2d3d6` |
| `RAG/bench/results/20260826_corpus-manifest.json` | 현재 코퍼스·인덱스·환경 manifest | `ef090e64bb74321156fcbb3d25751023a6bc53215d3ac0e5cd9c486a12c7b43c` |
| `RAG/bench/results/20260826_current-faiss-cpu-warm.json` | live FAISS CPU 참고 결과 | `86c58ccc379b96b37c7779a81d45e428afa6912ae62e4dedb8e2c410f066bb12` |
| `RAG/bench/results/20260826_current-faiss-gpu-warm-c20.json` | live FAISS CUDA 후보 20 참고 결과 | `19b1a3d4844d5fe83c24b8fd815105a55a8f639b8c51498e5fd828a298e66716` |
| `RAG/bench/results/20260826_controlled-summary.json` | 주 결과와 비교 상세, raw 해시 포함 | `38877ad0499002fa0253a966ed0d082d5e26e003afff4d6ea8440f87485345e8` |
| `RAG/bench/results/20260826_controlled-summary.csv` | 8개 행 표 형식 요약 | `c69c6ddd6b0d8b2ea88db7d4c913779686fb166eecc109dd62d23688e8f6ca82` |

통제 raw 파일:

| 조건 | 파일 | SHA-256 |
|---|---|---|
| FAISS CPU c10 | `20260826_controlled-faiss-cached-cpu-c10.json` | `58f8c2cd00e5a7e8fcf921514a3f3dcb0e3c7d177766c2cd8ff56fbfdb3cce62` |
| FAISS CPU c20 | `20260826_controlled-faiss-cached-cpu.json` | `b9aba6f5560f3235f138249d077fb5858b51142beaeea41de514b9e3b76c2f6c` |
| FAISS CUDA c10 | `20260826_controlled-faiss-cached-gpu-c10.json` | `557b5f9d7ab0bf87d5b52482da4bf7b89044e9309afc04bcfd3d466a06bec7fc` |
| FAISS CUDA c20 | `20260826_controlled-faiss-cached-gpu-c20.json` | `4951056d6d47f23989dbdc2a3cf9d718af8eef1d2e488ab70eddc211ebb55886` |
| Qdrant tuned CPU c10 | `20260826_controlled-qdrant-tuned-cpu-c10.json` | `1e2b1fa98d9bf1b2d9a7d199eae60e5c3afab4b145f6a6dc933bf56f8696b9ba` |
| Qdrant tuned CPU c20 | `20260826_controlled-qdrant-tuned-cpu.json` | `5081dac348bc69f5ec2c25c641e29102700461a7d45af609f47f9635459b1012` |
| Qdrant tuned CUDA c10 | `20260826_controlled-qdrant-tuned-gpu-c10.json` | `99ab07e7577b9a0f492ef0b9d74b7d58c98b03fd929f85a2cd6afa83091a6027` |
| Qdrant tuned CUDA c20 | `20260826_controlled-qdrant-tuned-gpu-c20.json` | `a604a8957fb5eb7ada592da7021d5cd18d1fa9a6a64f5e1e6c10234336fc79e9` |
| Qdrant naive CUDA c20 | `20260826_controlled-qdrant-naive-gpu-c20.json` | `91612acd39d7a05bce2f747e8add3bde5493f18f2c397356d7085664453548de` |

각 raw JSON에는 질문별 3회 타이밍, 단계별 타이밍, vector/final ranking과 signature,
quality 판정, Git·런타임 메타데이터가 들어 있다. 요약 JSON은 입력 raw 전체의
SHA-256을 다시 기록하므로 표의 값에서 원시 결과까지 추적할 수 있다.
