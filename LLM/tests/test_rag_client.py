from __future__ import annotations

import unittest

from app.domain import RetrievedChunk
from app.services.rag_client import _page_of, _to_chunks, unique_source_chunks


class PageContractTests(unittest.TestCase):
    def test_top_level_page_zero_is_displayed_as_first_page(self) -> None:
        self.assertEqual(_page_of({"page": 0}, {}), 1)

    def test_explicit_top_level_page_number_is_preferred_and_never_zero(self) -> None:
        self.assertEqual(
            _page_of(
                {"page_number": "7", "page_index": 2, "page": 3},
                {"page_number": 4, "page": 0},
            ),
            7,
        )
        self.assertEqual(_page_of({"page_number": 0}, {}), 1)

    def test_page_index_is_zero_based(self) -> None:
        self.assertEqual(_page_of({"page_index": 0}, {}), 1)
        self.assertEqual(_page_of({}, {"page_index": "4"}), 5)

    def test_metadata_page_is_zero_based(self) -> None:
        self.assertEqual(_page_of({}, {"page": 0}), 1)
        self.assertEqual(_page_of({}, {"page": 4}), 5)

    def test_legacy_metadata_page_number_copied_from_index_is_corrected(self) -> None:
        self.assertEqual(_page_of({}, {"page_number": 0, "page": 0}), 1)
        self.assertEqual(_page_of({}, {"page_number": 4, "page": 4}), 5)

    def test_corrected_metadata_page_number_is_not_incremented_twice(self) -> None:
        self.assertEqual(_page_of({}, {"page_number": 5, "page": 4}), 5)
        self.assertEqual(_page_of({}, {"page_number": 5}), 5)

    def test_invalid_page_is_not_displayed(self) -> None:
        self.assertIsNone(_page_of({"page": -1}, {"page": -1}))
        self.assertIsNone(_page_of({"page": True}, {"page": "not-a-number"}))


class ChunkConversionTests(unittest.TestCase):
    def test_distinct_chunks_on_same_page_are_retained_in_rank_order(self) -> None:
        results = [
            {
                "doc_id": 10,
                "content": "첫 번째 조문",
                "metadata": {"source_file": "복무규정.pdf", "page": 0},
            },
            {
                "doc_id": 10,
                "content": "같은 페이지의 다른 표 행",
                "metadata": {"source_file": "복무규정.pdf", "page": 0},
            },
            {
                "doc_id": 20,
                "content": "세 번째 결과",
                "metadata": {"source_file": "다른규정.pdf", "page": 1},
            },
        ]

        chunks = _to_chunks(results, top_k=2)

        self.assertEqual(
            [chunk.content for chunk in chunks],
            ["첫 번째 조문", "같은 페이지의 다른 표 행"],
        )
        self.assertEqual([chunk.page for chunk in chunks], [1, 1])

    def test_ui_source_deduplication_does_not_mutate_prompt_chunks(self) -> None:
        chunks = [
            RetrievedChunk("복무규정.pdf", "첫 청크", doc_id=10, page=1),
            RetrievedChunk("복무규정.pdf", "둘째 청크", doc_id=10, page=1),
            RetrievedChunk("복무규정.pdf", "다른 페이지", doc_id=10, page=2),
            RetrievedChunk("복무규정.pdf", "다른 문서 ID", doc_id=11, page=1),
        ]

        sources = unique_source_chunks(chunks)

        self.assertEqual(len(chunks), 4)
        self.assertEqual(
            [(chunk.doc_id, chunk.page, chunk.content) for chunk in sources],
            [(10, 1, "첫 청크"), (10, 2, "다른 페이지"), (11, 1, "다른 문서 ID")],
        )

    def test_retrieval_scope_metadata_is_preserved_for_the_prompt(self) -> None:
        chunks = _to_chunks(
            [
                {
                    "doc_id": 10,
                    "content": "육아휴직 조문",
                    "metadata": {
                        "source_file": "기술연구원 인사규정.pdf",
                        "page_number": 2,
                        "document_title": "기술연구원 인사규정",
                        "authority": "internal",
                        "audience": ["기술연구원"],
                        "article": "제20조(휴직)",
                        "section_type": "main",
                    },
                }
            ],
            top_k=5,
        )

        self.assertEqual(chunks[0].document_title, "기술연구원 인사규정")
        self.assertEqual(chunks[0].authority, "internal")
        self.assertEqual(chunks[0].audience, ("기술연구원",))
        self.assertEqual(chunks[0].article, "제20조(휴직)")

    def test_same_page_different_articles_remain_visible_sources(self) -> None:
        chunks = [
            RetrievedChunk(
                "복무규정.pdf",
                "연차 조문",
                doc_id=10,
                page=4,
                document_title="복무규정",
                article="제20조(연차휴가)",
            ),
            RetrievedChunk(
                "복무규정.pdf",
                "병가 조문",
                doc_id=10,
                page=4,
                document_title="복무규정",
                article="제21조(병가)",
            ),
        ]

        sources = unique_source_chunks(chunks)

        self.assertEqual([source.article for source in sources], ["제20조(연차휴가)", "제21조(병가)"])
        self.assertEqual(sources[1].to_source().document_title, "복무규정")
        self.assertEqual(sources[1].to_source().article, "제21조(병가)")


if __name__ == "__main__":
    unittest.main()
