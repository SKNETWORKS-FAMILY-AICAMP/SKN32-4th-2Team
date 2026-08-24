# Smart HR Qwen2.5-7B 한국어 SFT 추가 실험

> **결론: 운영에 채택하지 않았습니다.**
> 언어 이탈(6건→0건)과 주제 분류(33→35/35)는 해결됐지만, 사실성이 17/35 에 그치고
> (개선 6 · 회귀 4로 상쇄) 응답이 24% 느려졌습니다. 좋아진 지표만 보고 도입하지 않고
> 재본 뒤 판단한 결과입니다. 근거는 [reports/main35_ollama_comparison.md](reports/main35_ollama_comparison.md).
>
> 서비스 쪽 성능 비교표는 [../docs/PERFORMANCE_REPORT.md](../docs/PERFORMANCE_REPORT.md) 참조.

## 이 폴더에 없는 것 (재생성 대상)

용량이 커서 git 에 올리지 않았습니다. `.gitignore` 참조.

| 항목 | 크기 | 다시 만드는 법 |
|---|---|---|
| `outputs/` LoRA 어댑터 | 170MB | `train_qlora.py` |
| `tools/llama.cpp` | 201MB | `git clone` |
| `venv_convert/` | 168MB | `requirements.txt` |
| `ollama/*.gguf` | 78MB | llama.cpp 변환 (`ollama/build_manifest.json` 에 절차 기록) |
| `data/holdout.jsonl`, `corpus_cache.json` | 1.5MB | `export_holdout.py` |

**커밋된 것**: 학습·평가 스크립트, 검수 승인된 학습 데이터 100건(`data/candidates.jsonl`),
비교 보고서(`reports/*.md`), 재현에 필요한 해시·환경 기록.

---

이 폴더는 팀 발표의 OpenAI·Gemini 핵심 경로와 분리된 Qwen 추가 검증 트랙입니다.
팀 서비스 코드는 수정하지 않으며, 아래 순서로 품질이 증명된 뒤에만 Ollama 통합을
검토합니다.

```text
공식 HR PDF → 사람 검수 후보 100건 → 누수/PII 검사 → 7B QLoRA SFT
           → 같은 RunPod에서 Base/SFT 34문항×3회 비교
           → 블라인드 근거 검수 → 통과 시에만 Ollama 동일 장비 평가
```

## 현재 준비된 것

- 모델: `Qwen/Qwen2.5-7B-Instruct` (Hugging Face commit 고정)
- 4-bit NF4 QLoRA, LoRA rank 16
- system/user 토큰을 제외하고 assistant 답변 토큰만 학습
- train/valid `intent_group` 교차 금지
- 기존 34문항 완전 일치·유사 질문·그룹 누수 차단
- 주민등록번호·이메일·전화번호·사번 패턴 검사
- 모델 revision, 데이터·프롬프트 SHA-256, CUDA/GPU, 패키지 버전 기록
- 같은 GPU에서 Base와 SFT를 동일 생성 조건으로 평가
- 34문항 3회, 총 102답변의 한국어 이탈 자동 검사와 블라인드 수동 검수지 생성

## 로컬에서 먼저 할 일

팀 저장소의 평가 문항, 서비스 프롬프트, 이상적 RAG 문맥을 평가 전용 파일로
스냅샷합니다. 이 파일은 학습 데이터 생성 재료로 사용하면 안 됩니다.

```powershell
cd <저장소>\LLM\qwen-sft
python export_holdout.py --team-root ..\..
python export_source_inventory.py
python -m pytest -q
```

그다음 [data/candidates.jsonl](data/candidates.jsonl)을 공식 PDF 원문으로 작성하고
사람 검수가 끝난 행만 `approved: true`로 바꿉니다. 최소 기준은 train 80건,
valid 20건입니다. 데이터 규칙과 주제별 목표량은 [data/README.md](data/README.md),
[data/annotation_plan.yaml](data/annotation_plan.yaml)을 따릅니다.

```powershell
python prepare_dataset.py
```

## RunPod 실행

Pod 생성값과 생성 후 알려줘야 할 정보는 [RUNPOD.md](RUNPOD.md)에 정리했습니다.
학습 명령은 다음 순서입니다.

```bash
cd /workspace/qwen-sft
cp .env.example .env
python -m pip install -r requirements.txt
python check_environment.py
python -m pytest -q
python profile_token_lengths.py
python prepare_dataset.py
python train_qlora.py
python evaluate.py --variant base
python evaluate.py --variant sft
python evaluate_topic.py --variant base
python evaluate_topic.py --variant sft
python compare_results.py
```

## 채택 게이트

- 한국어 외 문장 혼입: 0/102
- 빈 답변·생성 오류: 0/102
- 문서 없음 질문에서 안전 안내 누락: 0건
- 개인 기록을 조회한 것처럼 임의 수치를 생성: 0건
- 문서에 없는 숫자·조문·절차 생성: 0건
- 34문항 전체 블라인드 근거 검수 완료
- 통과 후 로컬 Ollama 동일 하드웨어 평가에서 p95 5초 이하
- 최종 Ollama 경로의 주제 분류 정확도가 현재 기준선 32/34 아래로 하락하지 않음

RunPod Transformers 지연시간과 기존 로컬 Ollama 지연시간은 하드웨어와 양자화
방식이 다르므로 직접 비교하지 않습니다. 언어·근거 품질을 통과한 모델만 병합 및
GGUF/Ollama 변환 대상으로 올립니다.

## 이번 단계에서 하지 않는 것

- DPO: 고품질 chosen/rejected 쌍이 준비되기 전에는 수행하지 않습니다.
- 팀 `LLM/app` 수정: Qwen SFT가 검증을 통과하기 전에는 서비스에 연결하지 않습니다.
- 기존 34문항을 이용한 학습 데이터 생성: 평가 누수이므로 금지합니다.
