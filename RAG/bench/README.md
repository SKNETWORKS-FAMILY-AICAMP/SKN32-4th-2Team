# RAG API benchmark

이 디렉터리는 LLM 호출 없이 현재 FastAPI RAG의 `/api/search`만 측정합니다.
LLM API 비용과 응답 변동을 배제하고 검색 지연과 정답 문서 검색률을 함께 비교하기
위한 벤치마크입니다.

질문과 정답 문서명은 `LLM/bench/questions.yaml`의 35개 라벨 세트를 공유합니다.
정답 문서 중 하나가 검색 결과에 들어오면 source hit로 계산하며, 범위 밖 질문은
검색 품질 점수에서 제외합니다.

## 실행 전제

- `RAG/.venv`를 사용합니다. 별도 가상환경을 만들 필요가 없습니다.
- RAG 서버가 `http://127.0.0.1:8001`에서 실행 중이어야 합니다.
- `/health`가 `status=ok`, `models_ready=true`가 된 뒤 실행합니다.
- 이 테스트는 순차 요청의 사용자 체감 지연을 측정합니다. 동시 부하 테스트가 아닙니다.

GPU 실험에는 CUDA 지원 PyTorch가 같은 가상환경에 설치돼 있어야 합니다. 이 저장소의
2026-08-26 측정 환경은 `torch 2.13.0+cu130`이었습니다. 다른 PC에서는 PyTorch의
공식 설치 선택기에서 드라이버에 맞는 CUDA wheel을 고른 뒤 실제 연산까지 확인합니다.

```powershell
RAG\.venv\Scripts\python.exe -m pip install --upgrade torch `
  --index-url https://download.pytorch.org/whl/cu130

RAG\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

저장 없이 흐름만 빨리 확인하고 싶다면 결과 경로를 임시 위치로 지정합니다.

```powershell
RAG\.venv\Scripts\python.exe RAG\bench\run_api_bench.py `
  --label smoke --limit 1 --repeats 1 `
  --output $env:TEMP\rag-smoke.json
```

현재 warm 기준선은 다음처럼 측정합니다. 기본값은 문항당 3회입니다.

```powershell
RAG\.venv\Scripts\python.exe RAG\bench\run_api_bench.py `
  --label cpu-warm-baseline --repeats 3
```

코퍼스와 FAISS 인덱스가 같은 데이터인지 확인할 수 있는 manifest를 생성합니다.

```powershell
RAG\.venv\Scripts\python.exe RAG\bench\capture_manifest.py
```

FAISS/Qdrant와 CPU/GPU를 같은 검색 코드에서 비교할 때는 직접 backend 벤치를
사용합니다. 이 벤치는 매 실행을 새 프로세스에서 시작하며 LLM과 HTTP 서버가
필요하지 않습니다.

```powershell
RAG\.venv\Scripts\python.exe -m pip install -r RAG\bench\requirements.txt

RAG\.venv\Scripts\python.exe RAG\bench\run_backend_bench.py `
  --backend faiss-cached --device cpu --label controlled

RAG\.venv\Scripts\python.exe RAG\bench\run_backend_bench.py `
  --backend qdrant-tuned --device cuda --label controlled
```

최종 통제 비교는 각 명령을 clean Git 상태의 새 프로세스에서 실행하고 다음 8개 셀을
모두 채웁니다.

| 축 | 값 |
|---|---|
| backend | `faiss-cached`, `qdrant-tuned` |
| device | `cpu`, `cuda` |
| initial candidates | `20`, `10` |

각 셀은 워밍업 1회 후 35문항을 3회씩, 총 105회 측정합니다. CPU와 CUDA 실행을
동시에 돌리면 자원 경합으로 비교가 오염되므로 순차 실행합니다.

초기 후보 20개와 10개의 속도·품질 차이는 동일 명령에 다음 옵션만 바꿔
측정합니다. `top_k=5`는 유지됩니다. 이 값은 BM25 정규화 대상과 CrossEncoder
리랭커 입력을 함께 바꾸므로 최종 순위가 달라질 수 있습니다.

```powershell
RAG\.venv\Scripts\python.exe RAG\bench\run_backend_bench.py `
  --backend faiss-cached --device cpu --initial-candidates 10 `
  --label controlled-candidates10
```

지원 backend는 다음과 같습니다.

- `faiss-cached`: 현재 운영과 같은 문서별 FAISS 캐시
- `faiss-unified`: 기존 벡터를 한 개의 exact FAISS 인덱스로 합친 전역 top-20
- `qdrant-naive`: embedded in-memory exact Qdrant의 전역 top-20
- `qdrant-tuned`: Qdrant 상위 80개에서 문서당 3개, 전체 20개로 제한

`qdrant-*`는 독립 Qdrant 서버나 HNSW 성능이 아니라 로컬 exact 모드입니다.
GPU 비교는 CUDA 지원 PyTorch가 설치된 동일 `RAG/.venv`에서 실행해야 합니다.
FAISS와 embedded Qdrant 검색은 CPU에서 수행되며 GPU는 질문 임베딩과 CrossEncoder
리랭커를 가속합니다. 현재 운영 코드는 CPU 리랭커를 FP32, CUDA 리랭커를 FP16으로
실행하므로 결과는 순수 장치만의 차이가 아닌 `CPU FP32 ↔ GPU FP16` 운영 구성
비교입니다.

8개 raw 결과를 검증하고 보고서용 JSON/CSV를 만드는 명령은 다음과 같습니다.

```powershell
RAG\.venv\Scripts\python.exe RAG\bench\summarize_backend_results.py `
  --manifest RAG\bench\results\20260826_corpus-manifest.json `
  --supplemental RAG\bench\results\20260826_controlled-qdrant-naive-gpu-c20.json `
  RAG\bench\results\20260826_controlled-faiss-cached-cpu.json `
  RAG\bench\results\20260826_controlled-faiss-cached-cpu-c10.json `
  RAG\bench\results\20260826_controlled-faiss-cached-gpu-c20.json `
  RAG\bench\results\20260826_controlled-faiss-cached-gpu-c10.json `
  RAG\bench\results\20260826_controlled-qdrant-tuned-cpu.json `
  RAG\bench\results\20260826_controlled-qdrant-tuned-cpu-c10.json `
  RAG\bench\results\20260826_controlled-qdrant-tuned-gpu-c20.json `
  RAG\bench\results\20260826_controlled-qdrant-tuned-gpu-c10.json
```

집계기는 8개 셀의 Git 커밋/clean 상태, 질문 해시, 반복 수, top-k, 코퍼스 수량과
manifest 해시가 일치하지 않으면 결과 결합을 중단합니다.

다른 서버를 측정할 때는 `--base-url`을 지정합니다. 결과는 기본적으로
`RAG/bench/results/<시각>_<label>.json`에 저장됩니다.

## 결과 해석

- `summary.latency`: 모든 성공 요청의 min, p50, p95, max, mean
- `summary.quality.source_hit_at_1/3/5`: 정답 문서가 상위 k개 안에 한 개 이상 있는 비율
- `summary.quality.mean_reciprocal_rank`: 첫 정답 문서 순위를 반영한 MRR
- `unstable_rankings`: 반복 실행 사이 검색 순서가 달라진 질문 수
- `runtime`: Python, Torch, CUDA 사용 가능 여부, 로컬 인덱스 수
- `health`: 측정 직전 서버 준비 상태와 워밍업된 인덱스 수
- `git`: 측정 코드의 브랜치, 커밋, 미커밋 변경 여부

직접 backend 결과의 `summary.stages_ms`에는 `embed`, `vector_search`, `bm25`,
`rerank`, `finalize`, `total` 단계가 따로 기록됩니다. Qdrant의 Euclidean 거리는
FAISS `IndexFlatL2`와 숫자 단위가 다르므로 raw 값과 비교용 squared-L2를 모두
보존합니다.

현재 서버는 시작 시 FAISS 인덱스를 워밍업하므로 이 스크립트의 수치는 warm 검색
지연입니다. 서버 시작부터 ready까지 걸린 시간과 `RAG_WARM_VECTOR_STORES=0` 상태의
첫 요청은 별도 cold-start 실험으로 다뤄야 합니다.

조건을 비교할 때는 한 번에 하나만 바꾸고, 같은 질문 파일 해시·인덱스 수·top-k·
후보 수·장치(CPU/GPU)를 유지해야 합니다. 임베딩 모델이나 청킹 설정을 바꾸면 기존
FAISS 인덱스를 그대로 비교하지 말고 동일 코퍼스를 다시 인덱싱해야 합니다.
