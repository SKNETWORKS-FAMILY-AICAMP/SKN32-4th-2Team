"""학습 근거로 허용된 팀 RAG PDF의 파일·페이지·해시 목록을 만든다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pypdf

from src.io_utils import sha256_file, write_json

ROOT = Path(__file__).resolve().parent
DEFAULT_PDF_DIR = Path(
    r"C:\Dev_Tools\other_team_project\SKN32-3rd-2Team\RAG\res\pdf"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    args = parser.parse_args()
    if not args.pdf_dir.is_dir():
        raise FileNotFoundError(f"PDF 폴더가 없습니다: {args.pdf_dir}")

    documents = []
    for path in sorted(args.pdf_dir.glob("*.pdf")):
        reader = pypdf.PdfReader(str(path))
        documents.append(
            {
                "file": path.name,
                "pages": len(reader.pages),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    payload = {
        "purpose": "approved_evidence_source_inventory",
        "source_directory": str(args.pdf_dir.resolve()),
        "document_count": len(documents),
        "total_pages": sum(item["pages"] for item in documents),
        "total_bytes": sum(item["bytes"] for item in documents),
        "documents": documents,
    }
    output = ROOT / "data/source_inventory.json"
    write_json(output, payload)
    print(json.dumps({key: value for key, value in payload.items() if key != "documents"}, ensure_ascii=False, indent=2))
    print(f"목록: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

