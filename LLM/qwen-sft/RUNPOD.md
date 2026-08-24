# RunPod 생성 체크리스트

## 권장 Pod 설정

| 항목 | 권장값 |
|---|---|
| Pod 이름 | `smart-hr-qwen25-7b-qlora` |
| Template | 공식 RunPod PyTorch 최신 템플릿 |
| GPU 수 | 1개 |
| 비용 우선 GPU | RTX 4090 24GB |
| 안정성 우선 GPU | A40, A6000, L40 계열 48GB |
| 최소 VRAM | 24GB |
| Container Disk | 50GB |
| Volume Disk | 최소 50GB, 권장 100GB |
| Volume Mount | `/workspace` |
| 연결 | SSH `22/tcp` 권장 |
| 선택 포트 | Jupyter `8888/http`, TensorBoard `6006/http` |

실제 사내 문서나 검수 데이터가 비식별·합성 데이터가 아니라면 `Secure Cloud`를
선택하세요. 이번 실험 폴더, Hugging Face 캐시, 체크포인트, 어댑터, 평가 결과는
모두 영구 볼륨인 `/workspace` 아래에 둡니다.

## Pod 생성 후 사용자에게 받을 정보

비밀값은 보내지 말고 아래 정보만 전달해 주세요.

- Pod ID
- GPU 정확한 이름과 VRAM
- Secure Cloud 또는 Community Cloud
- PyTorch 템플릿 이름 또는 이미지 태그
- Container Disk와 Volume Disk 용량
- Network Volume 사용 여부
- Connect 화면의 SSH 접속 명령어 또는 Public IP와 외부 SSH 포트
- 실험 폴더를 올린 RunPod 경로
- 아래 명령의 출력

```bash
nvidia-smi
python --version
df -h /workspace
```

HF_TOKEN, RunPod API Key, SSH 개인키, SSH/Jupyter 비밀번호는 채팅으로 보내지 않습니다.
Qwen2.5-7B-Instruct는 공개 모델이라 `HF_TOKEN` 없이 다운로드할 수 있습니다. 토큰을
사용한다면 RunPod Secret에 Hugging Face Read 권한 토큰만 저장하세요.

## 파일 전달

우선순위는 다음과 같습니다.

1. Git 원격 저장소가 있으면 `/workspace`에서 clone
2. Git을 쓰지 않으면 `runpodctl`로 폴더 전송
3. SSH/SCP 전송

전송 후 경로 예시는 `/workspace/qwen-sft`입니다.

## 설치 및 검사

```bash
cd /workspace/qwen-sft
cp .env.example .env
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python check_environment.py
python -m pytest -q
```

`.env`의 `HF_HOME`과 `TORCH_HOME`은 모델 캐시가 Container Disk가 아닌
`/workspace/.cache`에 남도록 합니다. 다른 영구 볼륨 경로를 썼다면 함께 바꾸세요.

`requirements.txt`에는 torch가 없습니다. 공식 PyTorch 템플릿에 설치된 CUDA 호환
torch를 보존하기 위한 의도된 설정입니다.

## 학습과 평가

```bash
python prepare_dataset.py
python train_qlora.py
python evaluate.py --variant base
python evaluate.py --variant sft
python evaluate_topic.py --variant base
python evaluate_topic.py --variant sft
python compare_results.py
```

각 모델 평가는 기본적으로 34문항을 세 번씩 실행합니다. 처음에는 아래 명령으로
한 문항만 확인한 뒤 전체 평가를 수행할 수 있습니다.

```bash
python evaluate.py --variant base --limit 1 --repeats 1
python evaluate.py --variant sft --limit 1 --repeats 1
python evaluate_topic.py --variant base --limit 1
python evaluate_topic.py --variant sft --limit 1
```

## 저장공간 주의

- Pod를 Stop하면 GPU는 반납되고 Container Disk의 데이터는 잃을 수 있습니다.
- `/workspace` Volume에 저장한 데이터는 Stop 후에도 보존되도록 구성합니다.
- Pod를 Terminate하면 일반 Volume Disk도 삭제될 수 있습니다.
- 종료 전 `outputs/.../adapter_model.safetensors`, `run_manifest.json`, `reports/`를
  로컬이나 별도 저장소로 내려받으세요.
