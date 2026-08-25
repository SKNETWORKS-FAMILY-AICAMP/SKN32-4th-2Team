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

현재 서버는 시작 시 FAISS 인덱스를 워밍업하므로 이 스크립트의 수치는 warm 검색
지연입니다. 서버 시작부터 ready까지 걸린 시간과 `RAG_WARM_VECTOR_STORES=0` 상태의
첫 요청은 별도 cold-start 실험으로 다뤄야 합니다.

조건을 비교할 때는 한 번에 하나만 바꾸고, 같은 질문 파일 해시·인덱스 수·top-k·
후보 수·장치(CPU/GPU)를 유지해야 합니다. 임베딩 모델이나 청킹 설정을 바꾸면 기존
FAISS 인덱스를 그대로 비교하지 말고 동일 코퍼스를 다시 인덱싱해야 합니다.
