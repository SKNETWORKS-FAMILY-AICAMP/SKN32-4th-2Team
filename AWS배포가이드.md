# Smart HR 서비스 AWS 배포 가이드

**SKN32-4th-2Team** · 작성일: 2026-08-27

WEB · RAG · LLM 3-Tier 서비스의 로컬 컨테이너화부터 AWS 운영 배포 및 CI/CD 자동화까지

---

## 목차

1. [개요](#1-개요)
2. [시스템 아키텍처](#2-시스템-아키텍처)
3. [AWS 인프라 구성](#3-aws-인프라-구성)
4. [로컬 컨테이너화 및 검증](#4-로컬-컨테이너화-및-검증)
5. [시크릿 및 환경변수 관리](#5-시크릿-및-환경변수-관리)
6. [CI/CD 배포 파이프라인](#6-cicd-배포-파이프라인)
7. [운영 가이드 및 비용 관리](#7-운영-가이드-및-비용-관리)
8. [향후 개선 과제](#8-향후-개선-과제)

---

## 1. 개요

WEB(Django), RAG(FAISS 기반 문서 검색), LLM(외부 API 연동) 3개 서비스로 구성된 프로젝트를 로컬 Docker 환경에서 검증하고, AWS 프리티어(신규 크레딧 계정) 환경에 배포하기까지의 전체 과정을 정리한 배포 가이드다.

### 1.1 프로젝트 구조

```
Root
├── web/   (Django)
├── RAG/   (Flask, FAISS 기반 문서 검색)
├── LLM/   (FastAPI, 외부 LLM API 호출)
├── nginx/
├── scripts/
│   └── fetch_env.sh
├── docker-compose.yml
└── .github/workflows/deploy.yml
```

### 1.2 핵심 제약 조건

- MySQL은 WEB과 RAG가 공유하며, AWS RDS로 분리 운영
- LLM은 로컬 모델을 적재하지 않고 외부 API를 호출하는 구조 (GPU 불필요)
- AWS 계정은 2026년 8월 생성 — 신규 크레딧 기반 Free Plan(6개월, 최대 $200)이 적용되어, 인스턴스 유형이 프리티어 대상 목록으로 제한됨
- 각 서비스의 `.env`는 git에 포함하지 않고 AWS Systems Manager Parameter Store로 관리

---

## 2. 시스템 아키텍처

### 2.1 구성 요소

| 구성 요소 | 역할 | 배포 형태 |
|---|---|---|
| Nginx | Reverse Proxy, 정적 파일 서빙, 라우팅(/rag, /llm) | Docker 컨테이너 |
| WEB | Django 기반 사용자 화면, 인증, 세션, DB 접근 | Docker 컨테이너 |
| RAG | FAISS 벡터 검색, 문서 임베딩/부트스트랩 | Docker 컨테이너 |
| LLM | FastAPI, 외부 LLM API(OpenAI/Gemini) 연동 | Docker 컨테이너 |
| RDS(MySQL) | WEB/RAG 공용 데이터베이스 | AWS RDS 단일 인스턴스 |
| Parameter Store | 서비스별 .env 값(시크릿 포함) 저장 | AWS SSM |
| EC2 | 위 컨테이너 전체를 Docker Compose로 실행하는 호스트 | AWS EC2 단일 인스턴스 |

### 2.2 서비스 기동 순서

RAG의 문서 부트스트랩 스크립트가 WEB(Django)의 마이그레이션 결과 테이블에 의존하는 구조이므로, 기동 순서는 다음과 같이 고정한다.

```
RDS(외부, 상시 대기) → WEB(migrate) → RAG(bootstrap + FAISS) → LLM → Nginx
```

Docker Compose의 `depends_on: condition: service_healthy`와 각 서비스의 healthcheck 엔드포인트로 순서를 강제한다.

### 2.3 네트워크 구조 (VPC / Subnet)

```
AWS Cloud
└── VPC (A)
    ├── Public Subnet (인터넷 접근 가능)
    │   └── EC2 instance
    │       └── Docker Compose
    │           ├── Nginx (reverse proxy) — Port 80
    │           ├── web (Django)  — Port 8000
    │           ├── RAG (FAISS)   — Port 8001
    │           └── LLM (FastAPI) — Port 8002
    └── Private Subnet (인터넷 접근 불가 — 라우팅 테이블 미등록)
        └── Amazon RDS (MySQL) — Port 3306

AWS Account (VPC 밖 — 글로벌/리전 서비스)
├── Parameter Store
├── IAM Role: ec2-myapp (SSM + Parameter Store 읽기)
└── IAM Role: gh-oidc (SendCommand)
```

---

## 3. AWS 인프라 구성

### 3.1 네트워크 (VPC / 서브넷 / 보안그룹)

- 기존 VPC(A)와 public-subnet을 재사용
- RDS 서브넷 그룹은 서로 다른 가용영역(AZ) 2개 이상이 필수이므로, 기존 서브넷과 다른 AZ에 db-subnet1을 추가 생성
- db-subnet1은 라우팅 테이블에 등록하지 않아 사실상 프라이빗 서브넷으로 운용
- EC2 보안그룹: 인바운드 22(내 IP), 80/443(전체) 허용, 서비스 개별 포트(8000~8002)는 비노출
- RDS 보안그룹: 인바운드 3306을 EC2 보안그룹 ID 소스로만 허용 (IP 대역 직접 허용 금지)

### 3.2 RDS (MySQL)

| 항목 | 값 |
|---|---|
| 엔진 | MySQL 8.0.x |
| 인스턴스 클래스 | db.t4g.micro |
| 스토리지 | gp3, 20GB (자동 조정 비활성화) |
| 퍼블릭 액세스 | 아니요 |
| Multi-AZ | 아니요 (Single-AZ) |

DB 접속 계정은 마스터 계정을 앱에 직접 사용하지 않고, WEB/RAG 전용 최소 권한 계정(SELECT/INSERT/UPDATE/DELETE + DDL 일부)을 별도로 발급하여 사용한다.

### 3.3 EC2

신규 크레딧 계정의 Free Plan은 t3.medium 등 일부 인스턴스 유형을 지원하지 않는다. RAG의 임베딩 모델 로딩 과정에서 t3.small(2GB RAM)은 OOM(Exit Code 137)이 반복 발생하여, 동일하게 Free Plan 대상이면서 메모리가 더 넉넉한 **m7i-flex.large(2vCPU, 8GB RAM)**로 전환하였다.

| 항목 | 값 |
|---|---|
| AMI | Ubuntu Server 24.04 LTS (x86_64) |
| 인스턴스 유형 | m7i-flex.large (2vCPU / 8GB RAM) |
| 스토리지 | gp3, 20~30GB |
| 네트워크 | 기존 VPC(A) / public-subnet |
| IAM 인스턴스 프로파일 | ec2-myapp-role |

EC2 부팅 시 user-data 스크립트로 Docker, Docker Compose Plugin, AWS CLI, SSM Agent, git, jq를 자동 설치한다. 컨테이너화된 구조이므로 호스트에는 Nginx/MySQL/Python 런타임을 별도 설치하지 않는다.

### 3.4 IAM 구성

| Role | 용도 | 주요 권한 |
|---|---|---|
| ec2-myapp-role | EC2 인스턴스 프로파일 | AmazonSSMManagedInstanceCore, Parameter Store 읽기(ssm:GetParameter*), kms:Decrypt |
| skn-github-actions-ecr-oidc-role | GitHub Actions OIDC 인증 | ssm:SendCommand(대상 인스턴스 ARN 한정), ssm:GetCommandInvocation |

두 Role 모두 최소 권한 원칙을 적용한다. EC2 Role은 시크릿을 등록(PutParameter)할 수 없는 읽기 전용으로 구성하여, 인스턴스가 탈취되더라도 시크릿을 변조할 수 없도록 설계했다. Parameter Store 값 등록은 반드시 EC2 외부(로컬 PC 또는 AWS CloudShell)에서 관리자 권한으로 수행한다.

### 3.5 Parameter Store

경로는 프로젝트명을 기준으로 계층화한다.

```
/SKN32-4th-2Team/web/DB_HOST
/SKN32-4th-2Team/web/DB_USER
/SKN32-4th-2Team/web/DB_PASSWORD        (SecureString)
/SKN32-4th-2Team/rag/DB_HOST
/SKN32-4th-2Team/rag/RAG_CORS_ORIGINS
/SKN32-4th-2Team/llm/EXTERNAL_API_KEY    (SecureString)
```

---

## 4. 로컬 컨테이너화 및 검증

### 4.1 Dockerfile 원칙

- 서비스별 개별 Dockerfile 작성 (WEB/RAG/LLM)
- `.dockerignore`로 `.env`, `venv/`, `__pycache__`, `.git` 등을 이미지에서 제외
- mysqlclient 사용 서비스는 `default-libmysqlclient-dev`, `build-essential` 빌드 의존성 포함
- `uvicorn --reload` 등 개발용 옵션은 프로덕션 이미지에서 제거
- WEB은 Django 개발 서버 대신 gunicorn으로 프로덕션 기동

### 4.2 최초 세팅과 매 기동 작업의 분리

`migrate`, `collectstatic`처럼 멱등성 있는 작업은 entrypoint.sh에서 매번 실행하고, 문서 부트스트랩·벡터 인덱스 생성처럼 비용이 큰 1회성 작업은 결과물(`vector_store` 폴더) 존재 여부로 스킵 여부를 판단한다.

```bash
VECTOR_STORE_DIR="/app/vector_store"
if [ -z "$(ls -A "$VECTOR_STORE_DIR" 2>/dev/null)" ]; then
    python scripts/bootstrap_documents.py --apply
else
    echo "기존 vector_store 발견 - bootstrap 스킵"
fi
```

### 4.3 Docker Compose 및 Nginx

Nginx는 EC2에 직접 설치하지 않고 Docker 컨테이너로 통일하여 배포 일관성을 확보한다. 설정 파일은 호스트 볼륨 마운트로 관리하여 코드와 함께 버전 관리한다.

```nginx
location /rag/ {
    proxy_pass http://rag:8001/;
    proxy_read_timeout 150s;
}
location /llm/ { proxy_pass http://llm:8002/; }
location /static/ { alias /app/staticfiles/; }
location / { proxy_pass http://web:8000/; }
```

### 4.4 헬스체크 및 기동 순서

RAG는 FAISS 인덱스 로딩 및 임베딩 모델 초기화에 최초 1회 약 18~20분이 소요되므로, healthcheck의 `start_period`를 1200초로 설정하여 오탐(unhealthy 오판)을 방지한다.

| 서비스 | healthcheck 방식 | start_period |
|---|---|---|
| web | `curl -f http://localhost:8000/` | 15s |
| rag | `curl -f http://localhost:8001/health` | 1200s (최초 벡터스토어 생성 시간 반영) |
| llm | python urllib 기반 (이미지에 curl 미설치) | 15s |

### 4.5 RAG 벡터스토어 볼륨 캐싱

`vector_store` 폴더를 named volume(`rag_vector_store`)으로 마운트하여, 컨테이너 재생성/재배포 시에도 최초 1회 생성한 벡터 데이터를 재사용한다. 이를 통해 재배포 소요 시간을 18~20분에서 수십 초 이내로 단축했다.

---

## 5. 시크릿 및 환경변수 관리

각 서비스의 `.env`는 git에 포함하지 않으며, 배포 시점에 Parameter Store 값을 조합하여 생성한다. `fetch_env.sh`는 실행 인자(web/rag/llm, 소문자)를 실제 폴더명(web 소문자, RAG/LLM 대문자)에 매핑하여 올바른 위치에 파일을 생성한다.

```bash
#!/bin/bash
set -e
SERVICE=$1

case "$SERVICE" in
  web) FOLDER="web" ;;
  rag) FOLDER="RAG" ;;
  llm) FOLDER="LLM" ;;
  *) echo "Unknown service: $SERVICE"; exit 1 ;;
esac

OUT_FILE="${FOLDER}/.env"

aws ssm get-parameters-by-path \
  --path "/SKN32-4th-2Team/${SERVICE}" \
  --recursive \
  --with-decryption \
  --query "Parameters[]" \
  --output json | \
jq -r '.[] | "\(.Name | split("/") | last)=\(.Value)"' > "$OUT_FILE"

echo "Generated $OUT_FILE"
```

### 5.1 URL 값의 두 가지 기준

| 구분 | 예시 값 | 주소 기준 |
|---|---|---|
| 서버 간 호출 (백엔드→백엔드) | `DOC_API_BASE_URL=http://rag:8001` | Docker 서비스명 |
| 브라우저에서의 호출 (프론트엔드 JS) | `API_BASE_URL=/rag` | Nginx 경유 상대경로 |
| CORS 허용 origin | `RAG_CORS_ORIGINS=https://<도메인>` | 브라우저 주소창 기준 |

브라우저 JS가 Docker 내부 서비스명(`rag:8001`)을 직접 호출하면 `ERR_NAME_NOT_RESOLVED`가 발생한다. 프론트엔드는 항상 Nginx가 프록시하는 상대경로를 사용해야 하며, 이 값은 배포 환경이 바뀌어도 코드 변경 없이 그대로 동작한다.

---

## 6. CI/CD 배포 파이프라인

GitHub Actions에서 OIDC로 임시 자격증명을 획득하고, AWS SSM `send-command`로 EC2에 배포 명령을 전달한다. 영구 SSH 키나 22번 포트 상시 개방 없이 배포가 가능하다.

### 6.1 트리거 조건

`web/`, `RAG/`, `LLM/`, `nginx/`, `scripts/`, `docker-compose.yml` 중 하나라도 변경된 `main` 브랜치 push에 한해 워크플로우가 실행되도록 경로 필터를 적용한다.

### 6.2 배포 흐름

1. `configure-aws-credentials`(OIDC)로 `skn-github-actions-ecr-oidc-role` 위임
2. 배포 스크립트를 base64로 인코딩하여 SSM `send-command` 전달 (따옴표/개행 이스케이프 문제 원천 차단)
3. EC2에서 root가 아닌 ubuntu 사용자 권한으로 스크립트 실행 (git 저장소 소유자와 일치)
4. `git fetch && git reset --hard origin/main`으로 배포 서버를 원격 상태와 강제 동기화
5. `fetch_env.sh` 3회 실행 → `docker compose build && up -d`
6. `aws ssm wait command-executed`로 완료 대기 (WaiterConfig: 15s × 240회 = 3600s, SSM 명령 타임아웃과 일치)
7. `get-command-invocation`으로 실제 Status를 조회하여 Success가 아니면 워크플로우 실패 처리
8. 별도 verify 단계에서 `docker compose ps` 결과를 재조회하여 4개 서비스 기동 상태 확인

### 6.3 IAM 인라인 정책 (GitHub Actions Role)

```json
{
  "Effect": "Allow",
  "Action": ["ssm:SendCommand"],
  "Resource": [
    "arn:aws:ec2:ap-northeast-2:<ACCOUNT_ID>:instance/<INSTANCE_ID>",
    "arn:aws:ssm:ap-northeast-2::document/AWS-RunShellScript"
  ]
}
```

EC2 인스턴스를 재생성할 때마다 이 Resource의 Instance ID와 GitHub Secret `EC2_INSTANCE_ID`, 그리고 OIDC 신뢰 정책의 대상 브랜치(`sub` 조건)를 반드시 함께 갱신해야 한다.

---

## 7. 운영 가이드 및 비용 관리

### 7.1 인스턴스 운영

- 검증/개발 단계에서는 미사용 시 EC2를 중지(Stop)하여 컴퓨팅 비용 절감 (EBS 스토리지 비용은 중지 중에도 소액 발생)
- RDS는 중지 후 7일이 지나면 AWS가 자동으로 재시작하므로, 장기간 미사용 시 주기적으로 재중지 필요
- 인스턴스를 삭제(Terminate)하면 Instance ID와 EBS 데이터가 소실되므로, 재사용 목적이면 반드시 중지(Stop)를 사용

### 7.2 크레딧 관리

- AWS 계정은 신규 크레딧 체계(Free Plan, 최대 $200, 6개월 한도) 적용 대상
- AWS Budgets로 예산 알림을 설정하여 크레딧 소진을 사전에 감지
- Free Plan 대상 인스턴스 유형(t3.micro/small, t4g.micro/small, c7i-flex.large, m7i-flex.large)을 벗어나면 즉시 표준 과금이 적용되므로 인스턴스 유형 변경 시 반드시 확인

### 7.3 재시작 체크리스트

- EC2 재시작 시 퍼블릭 IP가 변경됨 (탄력적 IP 미사용, 접속 주소 재확인 필요)
- docker compose의 `restart: unless-stopped` 정책으로 EC2 재부팅 시 컨테이너 자동 기동
- RDS 엔드포인트는 중지/시작과 무관하게 고정되어 재확인 불필요

---

## 8. 향후 개선 과제

1. 도메인 연결 및 Nginx + Certbot(Docker) 기반 HTTPS 적용
2. 무중단 배포 구조 도입 (현재는 `docker compose up -d` 시 짧은 다운타임 발생)
3. 로컬 PC → RDS 직접 bootstrap 및 FAISS 인덱스 S3 캐싱 (신규 서버 최초 배포 시간 단축)
4. Rollback 워크플로우 추가 (특정 커밋 SHA 기준 재배포)
5. 트래픽 증가 시 ECS/Fargate 등 오케스트레이션 확장 검토
