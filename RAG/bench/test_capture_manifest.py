from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

try:
    from RAG.bench.capture_manifest import (
        aggregate_digest,
        collect_file_records,
        sha256_file,
    )
except ModuleNotFoundError:
    from capture_manifest import aggregate_digest, collect_file_records, sha256_file


class CaptureManifestHashTests(unittest.TestCase):
    def test_file_hash_and_records_use_sorted_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            later = root / "z.pdf"
            earlier = root / "nested" / "a.pdf"
            earlier.parent.mkdir()
            later.write_bytes(b"later")
            earlier.write_bytes(b"earlier")

            records = collect_file_records([later, earlier], root=root)

            self.assertEqual([record["path"] for record in records], ["nested/a.pdf", "z.pdf"])
            self.assertEqual(records[0]["size_bytes"], len(b"earlier"))
            self.assertEqual(records[0]["sha256"], hashlib.sha256(b"earlier").hexdigest())
            self.assertEqual(sha256_file(later), hashlib.sha256(b"later").hexdigest())

    def test_aggregate_digest_is_order_independent(self) -> None:
        records = [
            {"path": "b/index.pkl", "size_bytes": 2, "sha256": "b" * 64},
            {"path": "a/index.faiss", "size_bytes": 1, "sha256": "a" * 64},
        ]

        self.assertEqual(aggregate_digest(records), aggregate_digest(reversed(records)))

    def test_aggregate_digest_changes_with_path_size_or_hash(self) -> None:
        base = [{"path": "a.pdf", "size_bytes": 3, "sha256": "a" * 64}]
        changed_path = [{"path": "b.pdf", "size_bytes": 3, "sha256": "a" * 64}]
        changed_size = [{"path": "a.pdf", "size_bytes": 4, "sha256": "a" * 64}]
        changed_hash = [{"path": "a.pdf", "size_bytes": 3, "sha256": "b" * 64}]

        base_digest = aggregate_digest(base)
        self.assertNotEqual(base_digest, aggregate_digest(changed_path))
        self.assertNotEqual(base_digest, aggregate_digest(changed_size))
        self.assertNotEqual(base_digest, aggregate_digest(changed_hash))


if __name__ == "__main__":
    unittest.main()
