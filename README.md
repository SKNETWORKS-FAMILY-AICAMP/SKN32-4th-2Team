# Smart HR RAG 챗봇

사내 인사·총무 규정 PDF를 근거로 답변하는 Django 기반 RAG 챗봇입니다. 사용자·채팅 데이터는 MySQL에, 문서별 검색 인덱스는 각 PC의 FAISS `vector_store`에 저장합니다.

## 구성

```text
Django WEB (8000) → LLM FastAPI (8002) → RAG FastAPI (8001)
       │                                      ├─ MySQL: 사용자·채팅·document 메타데이터
       │                                      ├─ RAG/res/pdf: PDF 코퍼스
       └──────────────────────────────────────└─ RAG/vector_store: PC별 FAISS 인덱스
```

| 서비스 | 역할 | 실행 주소 |
| --- | --- | --- |
| `web/` | Django 5.2 웹 화면, 인증, 채팅·관리자 기능 | `http://127.0.0.1:8000` |
| `LLM/` | 답변 생성, 주제 분류, RAG 호출 | `http://127.0.0.1:8002` |
| `RAG/` | PDF 등록·색인·검색·재정렬 | `http://127.0.0.1:8001` |

## 가장 먼저 읽을 문서

새 PC·새 DB에서의 전체 준비 절차는 [SETUP.md](SETUP.md)가 기준입니다. 실제 DB 비밀번호와 API 키는 저장소에 넣지 말고 각 서비스의 `.env`에만 설정합니다.

주요 문서:

- [Django WEB README](web/README.md)
- [LLM README](LLM/README.md)
- [RAG README](RAG/README.md)
- [Django 이관·MySQL 통합 문서](README2.md)

## 첫 실행

처음 한 번은 MySQL 스키마와 PDF 검색 인덱스를 준비해야 합니다. RAG 서버는 부트스트랩이 끝날 때까지 켜지 않는 것을 권장합니다.

```powershell
# 1) MySQL의 빈 rag_chatbot_v4 DB를 준비하고, 각 서비스 .env를 설정한다.

# 2) Django가 공용 MySQL 테이블을 만든다.
cd D:\Dev_Tools\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py migrate --noinput
```

레거시 이관은 **이전 DB가 남아 있는 팀원만** PDF 부트스트랩 전에 한 번 수행합니다. 이관 범위는 사용자·로그인 이력·채팅방·채팅 메시지와 각 답변의 근거 표시 스냅샷인 `chat_source`입니다. RAG 문서 메타데이터 `document`는 옮기지 않습니다. 이전 DB가 없는 팀원은 다음 블록을 건너뜁니다. `web/.env`의 `LEGACY_DATABASE_URL`은 읽기 전용 원본이고 `DATABASE_URL`과 다른 물리 DB여야 합니다. 이전 DB에는 Django `migrate`를 실행하지 않습니다.

```powershell
cd D:\Dev_Tools\SKN32-4th-2Team\web
# 기본 dry-run: 결과만 확인
.\.venv-django\Scripts\python.exe manage.py import_legacy_data

# dry-run 결과를 검토한 뒤에만 새 운영 DB로 실제 이관
.\.venv-django\Scripts\python.exe manage.py import_legacy_data --apply
```

이관이 끝난 뒤에는 Django와 RAG 모두 새 운영 DB `rag_chatbot_v4`만 사용합니다. 이전 채팅의 근거 파일명·페이지 표시는 `chat_source`로 보존되지만, 그 안의 과거 `doc_id`는 새 RAG 문서와 연결하지 않습니다. RAG는 모든 팀원 PC에서 새 PDF 코퍼스와 새 인덱스로 시작합니다. 상세 절차는 [Django 이관·MySQL 통합 문서](README2.md)를 참고합니다.

현재 사용할 정본 PDF만 `RAG/res/pdf`에 준비한 뒤 `document` 행과 FAISS 인덱스를 새로 생성합니다. 기존 `RAG/vector_store`가 있다면 자동으로 재사용하거나 삭제하지 말고, 보존 필요성을 확인한 뒤 별도 백업 위치로 옮기거나 정리해 빈 상태로 만듭니다. 그 다음 기본 부트스트랩으로 새 인덱스를 만듭니다.

```powershell
cd D:\Dev_Tools\SKN32-4th-2Team\RAG
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply
```

`RAG/sql/rag_document.sql`은 과거의 일부 문서를 위한 `TRUNCATE` 포함 스크립트이므로 현재 초기화에는 실행하지 않습니다. PDF를 폴더에 복사한 것만으로는 검색되지 않으며, 위 부트스트랩이 DB 등록과 색인을 함께 수행합니다.

## 일반 실행

초기화가 완료된 뒤에는 MySQL을 실행하고 다음 순서로 서버만 켭니다. RAG 창에서 `RAG 워밍업 완료` 및 `Application startup complete`가 나온 뒤 다음 서버를 시작합니다.

```powershell
# 창 1 — RAG
cd D:\Dev_Tools\SKN32-4th-2Team\RAG
.\.venv\Scripts\python.exe app.py

# 창 2 — LLM
cd D:\Dev_Tools\SKN32-4th-2Team\LLM
.\.venv\Scripts\python.exe -m app.main

# 창 3 — Django WEB
cd D:\Dev_Tools\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

브라우저에서 `http://127.0.0.1:8000`으로 접속합니다. 각 서버는 해당 PowerShell 창에서 `Ctrl+C`로 종료합니다.

## PDF와 vector_store 안전 기준

부트스트랩이 검사하는 대상은 선택한 PDF 폴더이며, 기본값은 `RAG/res/pdf`입니다. 하위 폴더는 자동으로 스캔하지 않으므로 검색 대상 PDF만 이 폴더의 최상위에 둡니다. 보관·삭제 PDF는 이 폴더 밖 또는 하위 보관 폴더에 둡니다.

`document` 행과 PDF를 연결할 때 파일 경로와 원본 파일명을 함께 사용합니다. 따라서 다음 기준을 지켜야 합니다.

- “파일명 중복”은 이전 프로젝트 폴더 전체를 대상으로 검사한다는 뜻이 아니라, **현재 부트스트랩 PDF 폴더의 파일**과 새 DB의 활성 `document` 행 사이의 이름·경로 연결 기준입니다.
- 다른 위치에서 PDF를 가져올 때 같은 파일명이지만 내용이 다르면, 현재 도구는 파일 내용 해시를 비교하지 않아 기존 문서로 잘못 연결할 수 있습니다. RAG 시작 전에 정본 PDF 코퍼스를 하나로 정하고, 내용이 다른 파일은 이름을 바꿉니다.
- 기본 `--mode skip`은 유효한 `vector_store/<doc_id>`가 이미 있으면 재색인하지 않고 적재 상태만 복구할 수 있습니다. 따라서 RAG 최초 구축 전에는 기존 `vector_store`를 깨끗이 분리하고, 초기화가 끝난 뒤 청킹 규칙·청크 크기·오버랩·임베딩 모델을 변경했을 때는 반드시 `--apply --mode overwrite`를 사용합니다.
- `--mode overwrite`는 현재 설정으로 임시 인덱스를 완성한 뒤 같은 `doc_id`의 기존 인덱스를 교체하므로, 빌드 실패 시 기존 인덱스를 보존합니다. DB 행과 연결되지 않은 고아 `vector_store` 폴더는 자동 삭제하지 않습니다. 물리적으로 완전히 비운 RAG 작업 공간이 필요하면, 대상 폴더를 먼저 백업하거나 범위를 확인한 뒤 수동으로 정리합니다.

## 다시 부트스트랩해야 하는 경우

- 새 PC 또는 새 로컬 MySQL을 준비했을 때
- `RAG/vector_store`를 삭제했거나 새로 받은 환경일 때
- PDF를 `RAG/res/pdf`에 직접 추가했을 때
- 청킹·임베딩 모델·조문 머리 설정을 바꿔 재색인이 필요할 때 (`--apply --mode overwrite` 사용)

`vector_store`는 Git에 저장하지 않는 로컬 파일입니다. 같은 MySQL을 여러 팀원이 공유해도 각 팀원 PC에서는 한 번씩 부트스트랩을 실행해야 합니다. 팀이 같은 검색 결과를 재현하려면 PDF 코퍼스도 동일하게 커밋하거나 안전한 방식으로 공유해야 합니다.

## 검증 순서

1. `http://127.0.0.1:8001/health`에서 RAG 상태를 확인합니다.
2. `http://127.0.0.1:8002/health`에서 LLM과 RAG 연결 상태를 확인합니다.
3. Django에 로그인해 질문을 보내고 답변의 근거 문서가 표시되는지 확인합니다.

## Git 정책

커밋 대상은 코드, 마이그레이션, 실행 문서, 검증된 PDF 코퍼스입니다. `.env`, API 키, DB 자격 증명, 가상환경, 로그, `vector_store`, 로컬 벤치마크 원본은 커밋하지 않습니다.
