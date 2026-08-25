"""처음 한 번만 실행하는 PDF 문서 등록·FAISS 색인 도구.

이 스크립트는 ``res/pdf`` 아래의 PDF를 찾아 MySQL ``document`` 테이블에
안전하게 등록하고, 문서별 ``vector_store/<doc_id>`` FAISS 인덱스를 만든다.
기존 문서 행을 삭제하거나 ``TRUNCATE`` 하지 않으므로, 중단된 초기화를
같은 명령으로 다시 실행해도 아직 적재되지 않은 문서부터 이어서 처리한다.

실행 예시:
    python scripts/bootstrap_documents.py
    python scripts/bootstrap_documents.py --apply
    python scripts/bootstrap_documents.py --apply --mode overwrite
"""

from __future__ import annotations

import argparse
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mysql.connector
from mysql.connector import Error


RAG_ROOT = Path(__file__).resolve().parents[1]

# Windows Terminal과 CI 로그에서 한글 진행 메시지를 일관되게 출력한다.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

if str(RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(RAG_ROOT))

from config import Config  # noqa: E402  (RAG/.env를 읽기 위해 경로 설정 후 import)


class BootstrapError(RuntimeError):
    """사용자가 조치할 수 있는 초기화 오류."""


@dataclass(frozen=True)
class PdfDocument:
    path: Path
    db_path: str
    original_file_name: str
    stored_file_name: str


@dataclass
class BootstrapSummary:
    discovered: int = 0
    registered: int = 0
    reused: int = 0
    relocated: int = 0
    indexed: int = 0
    repaired: int = 0
    planned_indexes: int = 0
    skipped: int = 0
    failed: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PDF 폴더를 document 테이블과 FAISS vector_store에 최초 등록합니다.",
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=Path(Config.UPLOAD_DIR),
        help="등록할 PDF 폴더 (기본값: RAG_UPLOAD_DIR 또는 RAG/res/pdf)",
    )
    parser.add_argument(
        "--mode",
        choices=("skip", "overwrite"),
        default="skip",
        help=(
            "skip: 정상적으로 적재된 문서는 건너뜀 (기본값), "
            "overwrite: 찾은 모든 PDF의 인덱스를 다시 만듦"
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="DB 문서 등록과 FAISS 색인을 실제로 수행함 (기본값은 안전한 dry-run)",
    )
    return parser.parse_args()


def path_for_database(pdf_path: Path) -> str:
    """팀원 PC마다 달라지는 절대 경로 대신 가능하면 RAG 상대 경로를 저장한다."""
    try:
        return pdf_path.relative_to(RAG_ROOT).as_posix()
    except ValueError:
        return str(pdf_path)


def absolute_database_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = RAG_ROOT / path
    return str(path.resolve()).casefold()


def scan_pdf_documents(pdf_dir: Path) -> list[PdfDocument]:
    pdf_dir = pdf_dir.expanduser().resolve()
    if not pdf_dir.is_dir():
        raise BootstrapError(f"PDF 폴더를 찾을 수 없습니다: {pdf_dir}")

    documents: list[PdfDocument] = []
    duplicate_names: dict[str, list[Path]] = {}

    for candidate in sorted(pdf_dir.glob("*.pdf"), key=lambda item: item.as_posix().casefold()):
        if not candidate.is_file() or candidate.suffix.lower() != ".pdf":
            continue

        pdf_path = candidate.resolve()
        duplicate_names.setdefault(pdf_path.name, []).append(pdf_path)
        prefix = "common_" if pdf_path.name[:1].isdigit() else "doc_"
        documents.append(
            PdfDocument(
                path=pdf_path,
                db_path=path_for_database(pdf_path),
                original_file_name=pdf_path.name,
                stored_file_name=f"{prefix}{pdf_path.name}",
            )
        )

    duplicated = {name: paths for name, paths in duplicate_names.items() if len(paths) > 1}
    if duplicated:
        details = "\n".join(
            f"  - {name}: {', '.join(str(path) for path in paths)}"
            for name, paths in duplicated.items()
        )
        raise BootstrapError(
            "같은 파일명을 가진 PDF가 둘 이상 있습니다. 문서 관리 API가 파일명으로 "
            f"중복을 판단하므로 이름을 고친 뒤 다시 실행하세요.\n{details}"
        )

    if not documents:
        raise BootstrapError(f"등록할 PDF가 없습니다: {pdf_dir}")

    return documents


def connect_database():
    try:
        return mysql.connector.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME,
        )
    except Error as exc:
        raise BootstrapError(
            "MySQL 연결에 실패했습니다. RAG/.env의 RAG_DB_* 값과 MySQL 실행 상태를 "
            f"확인하세요. ({exc})"
        ) from exc


def fetch_active_documents(connection: Any) -> list[dict[str, Any]]:
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT doc_id, original_file_name, stored_file_name, file_path,
                   is_loaded, is_deleted
            FROM document
            WHERE is_deleted = FALSE
            """
        )
        return cursor.fetchall()
    except Error as exc:
        raise BootstrapError(
            "document 테이블을 읽을 수 없습니다. 먼저 web 폴더에서 "
            "`python manage.py migrate --noinput`을 실행하세요. "
            f"({exc})"
        ) from exc
    finally:
        cursor.close()


def index_existing_documents(rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    by_path: dict[str, list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_path.setdefault(absolute_database_path(str(row["file_path"])), []).append(row)
        by_name.setdefault(str(row["original_file_name"]), []).append(row)
    return by_path, by_name


def choose_existing_row(
    pdf: PdfDocument,
    by_path: dict[str, list[dict[str, Any]]],
    by_name: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    path_matches = by_path.get(absolute_database_path(pdf.db_path), [])
    name_matches = by_name.get(pdf.original_file_name, [])
    matches = {int(row["doc_id"]): row for row in [*path_matches, *name_matches]}

    if len(matches) > 1:
        ids = ", ".join(str(doc_id) for doc_id in sorted(matches))
        raise BootstrapError(
            f"'{pdf.original_file_name}'에 연결된 활성 document 행이 여러 개입니다 "
            f"(doc_id: {ids}). 중복 행을 정리한 뒤 다시 실행하세요."
        )

    return next(iter(matches.values()), None)


def register_documents(
    connection: Any,
    pdfs: list[PdfDocument],
    *,
    dry_run: bool,
    summary: BootstrapSummary,
) -> list[tuple[PdfDocument, dict[str, Any]]]:
    existing_rows = fetch_active_documents(connection)
    by_path, by_name = index_existing_documents(existing_rows)
    cursor = connection.cursor(dictionary=True)
    entries: list[tuple[PdfDocument, dict[str, Any]]] = []

    try:
        for pdf in pdfs:
            row = choose_existing_row(pdf, by_path, by_name)
            if row is None:
                summary.registered += 1
                if dry_run:
                    entries.append(
                        (
                            pdf,
                            {
                                "doc_id": None,
                                "is_loaded": False,
                                "file_path": pdf.db_path,
                                "stored_file_name": pdf.stored_file_name,
                            },
                        )
                    )
                    continue

                cursor.execute(
                    """
                    INSERT INTO document
                        (original_file_name, stored_file_name, file_path, is_loaded, loaded_at)
                    VALUES (%s, %s, %s, FALSE, NULL)
                    """,
                    (pdf.original_file_name, pdf.stored_file_name, pdf.db_path),
                )
                connection.commit()
                row = {
                    "doc_id": cursor.lastrowid,
                    "is_loaded": False,
                    "file_path": pdf.db_path,
                    "stored_file_name": pdf.stored_file_name,
                }
                by_path.setdefault(absolute_database_path(pdf.db_path), []).append(row)
                by_name.setdefault(pdf.original_file_name, []).append(row)
            else:
                summary.reused += 1
                path_changed = absolute_database_path(str(row["file_path"])) != absolute_database_path(pdf.db_path)
                stored_name_changed = str(row["stored_file_name"]) != pdf.stored_file_name
                if path_changed or stored_name_changed:
                    summary.relocated += 1
                    if not dry_run:
                        cursor.execute(
                            """
                            UPDATE document
                            SET file_path = %s, stored_file_name = %s
                            WHERE doc_id = %s
                            """,
                            (pdf.db_path, pdf.stored_file_name, row["doc_id"]),
                        )
                        connection.commit()
                    row["file_path"] = pdf.db_path
                    row["stored_file_name"] = pdf.stored_file_name

            entries.append((pdf, row))
    except Error:
        connection.rollback()
        raise
    finally:
        cursor.close()

    return entries


def vector_path_for(doc_id: int) -> Path:
    vector_root = (RAG_ROOT / "vector_store").resolve()
    vector_path = (vector_root / str(doc_id)).resolve()
    if vector_path.parent != vector_root:
        raise BootstrapError(f"안전하지 않은 vector_store 경로입니다: {vector_path}")
    return vector_path


def is_valid_vector_store(vector_path: Path) -> bool:
    return (vector_path / "index.faiss").is_file() and (vector_path / "index.pkl").is_file()


def replace_vector_store(temporary_path: Path, target_path: Path) -> None:
    """성공한 임시 인덱스만 실제 경로로 교체하고, 교체 실패 시 기존 것을 복구한다."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = target_path.parent / f".bootstrap-backup-{target_path.name}-{uuid.uuid4().hex}"
    target_was_present = target_path.exists()

    if target_was_present:
        target_path.replace(backup_path)

    try:
        temporary_path.replace(target_path)
    except Exception:
        if target_was_present and backup_path.exists():
            backup_path.replace(target_path)
        raise
    else:
        if target_was_present and backup_path.exists():
            shutil.rmtree(backup_path)


def build_indexes(
    connection: Any,
    entries: list[tuple[PdfDocument, dict[str, Any]]],
    *,
    mode: str,
    dry_run: bool,
    summary: BootstrapSummary,
) -> None:
    if dry_run:
        for pdf, row in entries:
            doc_id = row.get("doc_id")
            vector_path = vector_path_for(int(doc_id)) if doc_id is not None else None
            index_exists = vector_path is not None and is_valid_vector_store(vector_path)
            currently_loaded = bool(row.get("is_loaded", False))
            should_build = mode == "overwrite" or not currently_loaded or not index_exists
            if should_build:
                summary.planned_indexes += 1
            else:
                summary.skipped += 1
        print("\n[dry-run] DB 등록 및 FAISS 색인은 수행하지 않았습니다.")
        return

    # 대형 모델은 한 번만 로드되고 모든 PDF에서 재사용된다.
    from rag_pipeline import build_vector_store_from_file

    cursor = connection.cursor()
    try:
        total = len(entries)
        for number, (pdf, row) in enumerate(entries, start=1):
            doc_id = int(row["doc_id"])
            vector_path = vector_path_for(doc_id)
            currently_loaded = bool(row.get("is_loaded", False))
            index_exists = is_valid_vector_store(vector_path)
            should_build = mode == "overwrite" or not currently_loaded or not index_exists

            if not should_build:
                summary.skipped += 1
                print(f"[{number}/{total}] 건너뜀 doc_id={doc_id}: {pdf.original_file_name}")
                continue

            if mode == "skip" and index_exists and not currently_loaded:
                cursor.execute(
                    """
                    UPDATE document
                    SET is_loaded = TRUE, loaded_at = COALESCE(loaded_at, CURRENT_TIMESTAMP)
                    WHERE doc_id = %s
                    """,
                    (doc_id,),
                )
                connection.commit()
                row["is_loaded"] = True
                summary.repaired += 1
                print(f"[{number}/{total}] 상태 복구 doc_id={doc_id}: {pdf.original_file_name}")
                continue

            print(f"[{number}/{total}] 색인 중 doc_id={doc_id}: {pdf.original_file_name}", flush=True)
            temporary_path: Path | None = None
            try:
                # 인덱스가 없는데 DB만 loaded인 불일치는 먼저 바로잡는다.
                if currently_loaded and not index_exists:
                    cursor.execute(
                        "UPDATE document SET is_loaded = FALSE, loaded_at = NULL WHERE doc_id = %s",
                        (doc_id,),
                    )
                    connection.commit()

                temporary_path = vector_path.parent / f".bootstrap-{doc_id}-{uuid.uuid4().hex}"

                chunk_count = build_vector_store_from_file(
                    str(pdf.path),
                    str(temporary_path),
                    doc_id=doc_id,
                    chunk_size=Config.CHUNK_SIZE,
                    chunk_overlap=Config.CHUNK_OVERLAP,
                )
                if not is_valid_vector_store(temporary_path):
                    raise BootstrapError("FAISS 인덱스 파일(index.faiss/index.pkl)이 완성되지 않았습니다")

                replace_vector_store(temporary_path, vector_path)
                cursor.execute(
                    """
                    UPDATE document
                    SET is_loaded = TRUE, loaded_at = CURRENT_TIMESTAMP
                    WHERE doc_id = %s
                    """,
                    (doc_id,),
                )
                connection.commit()
                row["is_loaded"] = True
                summary.indexed += 1
                print(f"           완료: {chunk_count} chunks")
            except Exception as exc:  # 한 문서 실패가 전체 초기화를 막지 않게 한다.
                connection.rollback()
                if temporary_path is not None and temporary_path.exists():
                    shutil.rmtree(temporary_path)
                summary.failed += 1
                print(f"           실패: {exc}", file=sys.stderr)
    finally:
        cursor.close()


def print_summary(summary: BootstrapSummary, *, dry_run: bool) -> None:
    title = "DRY RUN 결과" if dry_run else "초기화 결과"
    print(f"\n{title}")
    print(f"- 발견한 PDF: {summary.discovered}")
    print(f"- 새 DB 등록: {summary.registered}")
    print(f"- 기존 DB 행 재사용: {summary.reused}")
    print(f"- 현재 PC 경로로 갱신: {summary.relocated}")
    if not dry_run:
        print(f"- 새로 색인: {summary.indexed}")
        print(f"- 기존 인덱스 상태 복구: {summary.repaired}")
        print(f"- 이미 정상이라 건너뜀: {summary.skipped}")
        print(f"- 색인 실패: {summary.failed}")
    else:
        print(f"- 이번 실행에서 색인 예정: {summary.planned_indexes}")
        print(f"- 이미 정상이라 건너뜀 예정: {summary.skipped}")


def main() -> int:
    args = parse_args()
    dry_run = not args.apply
    summary = BootstrapSummary()

    try:
        pdfs = scan_pdf_documents(args.pdf_dir)
        summary.discovered = len(pdfs)
        print(f"PDF {summary.discovered}개를 확인했습니다: {Path(args.pdf_dir).expanduser().resolve()}")
        print(f"대상 DB: {Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}")
        if dry_run:
            print("안전 미리보기 모드입니다. 실제 등록·색인은 --apply를 붙여 실행하세요.")

        connection = connect_database()
        try:
            entries = register_documents(
                connection,
                pdfs,
                dry_run=dry_run,
                summary=summary,
            )
            build_indexes(
                connection,
                entries,
                mode=args.mode,
                dry_run=dry_run,
                summary=summary,
            )
        finally:
            connection.close()

        print_summary(summary, dry_run=dry_run)
        if summary.failed:
            print("실패한 문서는 is_loaded=FALSE 상태입니다. 원인을 해결한 뒤 같은 명령으로 재실행하세요.")
            return 1
        return 0
    except BootstrapError as exc:
        print(f"초기화 중단: {exc}", file=sys.stderr)
        return 2
    except Error as exc:
        print(f"MySQL 오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
