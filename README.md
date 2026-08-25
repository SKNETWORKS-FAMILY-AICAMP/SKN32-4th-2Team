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

새 PC·새 DB에서의 전체 준비 절차는 [RAG/SETUP.md](RAG/SETUP.md)가 기준입니다. 실제 DB 비밀번호와 API 키는 저장소에 넣지 말고 각 서비스의 `.env`에만 설정합니다.

주요 문서:

- [Django WEB README](web/README.md)
- [LLM README](LLM/README.md)
- [RAG README](RAG/README.md)
- [Django 이관·MySQL 통합 문서](README2.md)

## 첫 실행

처음 한 번은 MySQL 스키마와 PDF 검색 인덱스를 준비해야 합니다. RAG 서버는 부트스트랩이 끝날 때까지 켜지 않는 것을 권장합니다.

```powershell
# 1) MySQL의 빈 rag_chatbot DB를 준비하고, 각 서비스 .env를 설정한다.

# 2) Django가 공용 MySQL 테이블을 만든다.
cd D:\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py migrate --noinput

# 3) PDF 목록을 확인한 뒤 document 행과 FAISS 인덱스를 생성한다.
cd ..\RAG
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py
.\.venv\Scripts\python.exe scripts\bootstrap_documents.py --apply
```

`RAG/sql/rag_document.sql`은 과거의 일부 문서를 위한 `TRUNCATE` 포함 스크립트이므로 현재 초기화에는 실행하지 않습니다. PDF를 폴더에 복사한 것만으로는 검색되지 않으며, 위 부트스트랩이 DB 등록과 색인을 함께 수행합니다.

## 일반 실행

초기화가 완료된 뒤에는 MySQL을 실행하고 다음 순서로 서버만 켭니다. RAG 창에서 `RAG 워밍업 완료` 및 `Application startup complete`가 나온 뒤 다음 서버를 시작합니다.

```powershell
# 창 1 — RAG
cd D:\SKN32-4th-2Team\RAG
.\.venv\Scripts\python.exe app.py

# 창 2 — LLM
cd D:\SKN32-4th-2Team\LLM
.\.venv\Scripts\python.exe -m app.main

# 창 3 — Django WEB
cd D:\SKN32-4th-2Team\web
.\.venv-django\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

브라우저에서 `http://127.0.0.1:8000`으로 접속합니다. 각 서버는 해당 PowerShell 창에서 `Ctrl+C`로 종료합니다.

## 다시 부트스트랩해야 하는 경우

- 새 PC 또는 새 로컬 MySQL을 준비했을 때
- `RAG/vector_store`를 삭제했거나 새로 받은 환경일 때
- PDF를 `RAG/res/pdf`에 직접 추가했을 때
- 청킹·임베딩 모델·조문 머리 설정을 바꿔 재색인이 필요할 때

`vector_store`는 Git에 저장하지 않는 로컬 파일입니다. 같은 MySQL을 여러 팀원이 공유해도 각 팀원 PC에서는 한 번씩 부트스트랩을 실행해야 합니다. 팀이 같은 검색 결과를 재현하려면 PDF 코퍼스도 동일하게 커밋하거나 안전한 방식으로 공유해야 합니다.

## 검증 순서

1. `http://127.0.0.1:8001/health`에서 RAG 상태를 확인합니다.
2. `http://127.0.0.1:8002/health`에서 LLM과 RAG 연결 상태를 확인합니다.
3. Django에 로그인해 질문을 보내고 답변의 근거 문서가 표시되는지 확인합니다.

## Git 정책

커밋 대상은 코드, 마이그레이션, 실행 문서, 검증된 PDF 코퍼스입니다. `.env`, API 키, DB 자격 증명, 가상환경, 로그, `vector_store`, 로컬 벤치마크 원본은 커밋하지 않습니다.
