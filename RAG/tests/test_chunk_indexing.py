from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from rag_pipeline import (
    DocumentLike,
    _article_heads,
    _normalize_whitespace,
    build_chunks_from_pages,
    preprocess_pages,
)


def _page(text: str, **metadata) -> DocumentLike:
    return DocumentLike(page_content=text, metadata=metadata)


class ArticleStructureTests(unittest.TestCase):
    def test_ocr_spacing_and_sub_article_are_canonicalized(self) -> None:
        heads = _article_heads(
            "제 1 0 조 의 2 （ 육아 휴직의 기간 ） 본문\n"
            "제 1 4 조 2 ( 시험관리위원 ) 본문"
        )

        self.assertEqual(heads[0], (0, "제10조의2(육아 휴직의 기간)"))
        self.assertEqual(heads[1][1], "제14조의2(시험관리위원)")

    def test_deleted_article_without_title_is_kept_as_own_section(self) -> None:
        page = _page(
            "제14조의2(시험관리위원)\n위원의 역할을 정한다.\n"
            "제 15 조 <삭제 2025.06.01.>\n"
            "제16조(합격결정)\n합격 기준을 정한다.",
            source="rules.pdf",
            page=0,
        )

        with patch.dict(os.environ, {"RAG_MIN_CHUNK_LENGTH": "1"}):
            chunks = build_chunks_from_pages([page], chunk_size=1000, chunk_overlap=0)

        self.assertEqual(
            [chunk.metadata["article"] for chunk in chunks],
            ["제14조의2(시험관리위원)", "제15조", "제16조(합격결정)"],
        )

    def test_whitespace_normalization_preserves_article_boundaries(self) -> None:
        normalized = _normalize_whitespace(
            "문서 제목\n제 1 조 ( 목적 )\n이 규정의 목적을 정한다.\n"
            "제 2 조 의 1 ( 적용 범위 )\n모든 직원에게 적용한다."
        )

        self.assertIn("\n제1조(목적)\n", normalized)
        self.assertIn("\n제2조의1(적용 범위)\n", normalized)

    def test_articles_are_not_recombined_when_chunk_size_is_large(self) -> None:
        page = _page(
            "제1조(목적)\n첫 번째 조문의 본문입니다.\n"
            "제2조(적용범위)\n두 번째 조문의 본문입니다.",
            source="rules.pdf",
            page=0,
        )

        with patch.dict(os.environ, {"RAG_MIN_CHUNK_LENGTH": "1"}):
            chunks = build_chunks_from_pages([page], chunk_size=1000, chunk_overlap=0)

        articles = [chunk.metadata["article"] for chunk in chunks]
        self.assertEqual(articles, ["제1조(목적)", "제2조(적용범위)"])
        self.assertTrue(
            all(not ("제1조(목적)" in chunk.page_content and "제2조(적용범위)" in chunk.page_content)
                for chunk in chunks)
        )


class PageMetadataTests(unittest.TestCase):
    def test_document_scope_metadata_is_attached_from_filename(self) -> None:
        document = preprocess_pages(
            [_page("직원 규정 본문", source="기술연구원 인사규정.pdf", page=0)]
        )[0]

        self.assertEqual(document.metadata["document_title"], "기술연구원 인사규정")
        self.assertEqual(document.metadata["authority"], "internal")
        self.assertEqual(document.metadata["audience"], ["기술연구원"])

    def test_pypdf_zero_based_pages_get_one_based_display_numbers(self) -> None:
        documents = preprocess_pages(
            [
                _page("첫 페이지 본문", source="rules.pdf", page=0),
                _page("둘째 페이지 본문", source="rules.pdf", page=1),
            ]
        )

        self.assertEqual(
            [(doc.metadata["page_index"], doc.metadata["page_number"]) for doc in documents],
            [(0, 1), (1, 2)],
        )

    def test_legacy_one_based_pages_are_detected_from_sequence(self) -> None:
        documents = preprocess_pages(
            [
                _page("첫 페이지 본문", source="rules.pdf", page=1),
                _page("둘째 페이지 본문", source="rules.pdf", page=2),
            ]
        )

        self.assertEqual(
            [(doc.metadata["page_index"], doc.metadata["page_number"]) for doc in documents],
            [(0, 1), (1, 2)],
        )

    def test_explicit_page_fields_take_precedence(self) -> None:
        document = preprocess_pages(
            [
                _page(
                    "표시 번호가 다른 페이지",
                    source="rules.pdf",
                    page=999,
                    page_index=7,
                    page_number=20,
                )
            ]
        )[0]

        self.assertEqual(document.metadata["page_index"], 7)
        self.assertEqual(document.metadata["page_number"], 20)
        self.assertEqual(document.metadata["page"], 7)


class SupplementAndTableTests(unittest.TestCase):
    def test_article_carry_stops_at_appendix_and_stays_stopped_on_next_page(self) -> None:
        pages = [
            _page("제7조(징계)\n직원 징계의 기준을 정한다.", source="rules.pdf", page=0),
            _page("이 문장은 제7조에서 계속되는 내용이다.", source="rules.pdf", page=1),
            _page(
                "[별표 1]\n구분    처분\n최초    견책-감봉",
                source="rules.pdf",
                page=2,
            ),
            _page("재범    정직-해임", source="rules.pdf", page=3),
            _page("[별지서식]개인정보 수집 동의서", source="rules.pdf", page=4),
            _page("(별표4의3) 음주운전 징계양정기준", source="rules.pdf", page=5),
            _page("(서식제8호) 직원 근무평정서", source="rules.pdf", page=6),
        ]

        with patch.dict(os.environ, {"RAG_MIN_CHUNK_LENGTH": "1"}):
            chunks = build_chunks_from_pages(pages, chunk_size=1000, chunk_overlap=0)

        by_page = {}
        for chunk in chunks:
            by_page.setdefault(chunk.metadata["page_index"], []).append(chunk)

        self.assertTrue(all(chunk.metadata["article"] == "제7조(징계)" for chunk in by_page[1]))
        self.assertTrue(all(chunk.metadata["article"] is None for chunk in by_page[2]))
        self.assertTrue(all(chunk.metadata["article"] is None for chunk in by_page[3]))
        self.assertTrue(all(chunk.metadata["article"] is None for chunk in by_page[4]))
        self.assertTrue(all(chunk.metadata["article"] is None for chunk in by_page[5]))
        self.assertTrue(all(chunk.metadata["article"] is None for chunk in by_page[6]))
        self.assertTrue(
            all(chunk.metadata["section_type"] == "appendix_table" for chunk in by_page[2] + by_page[3])
        )
        self.assertTrue(all("구분 | 처분" in chunk.page_content for chunk in by_page[3]))
        self.assertTrue(all(chunk.metadata["section_type"] == "attachment" for chunk in by_page[4]))
        self.assertTrue(all(chunk.metadata["section_type"] == "appendix_table" for chunk in by_page[5]))
        self.assertTrue(all(chunk.metadata["section_type"] == "form" for chunk in by_page[6]))

    def test_supplement_resets_main_article_before_new_supplement_article(self) -> None:
        pages = [
            _page("제9조(효력)\n본문의 효력을 정한다.", source="rules.pdf", page=0),
            _page("부 칙\n이 규정은 공포한 날부터 적용한다.", source="rules.pdf", page=1),
            _page("제 1 조 ( 시행일 )\n2026년 1월 1일부터 시행한다.", source="rules.pdf", page=2),
        ]

        with patch.dict(os.environ, {"RAG_MIN_CHUNK_LENGTH": "1"}):
            chunks = build_chunks_from_pages(pages, chunk_size=1000, chunk_overlap=0)

        page_one = [chunk for chunk in chunks if chunk.metadata["page_index"] == 1]
        page_two = [chunk for chunk in chunks if chunk.metadata["page_index"] == 2]
        self.assertTrue(all(chunk.metadata["article"] is None for chunk in page_one))
        self.assertTrue(all(chunk.metadata["section_type"] == "supplementary" for chunk in page_one))
        self.assertTrue(all(chunk.metadata["article"] == "제1조(시행일)" for chunk in page_two))
        self.assertTrue(all(chunk.metadata["section_type"] == "supplementary" for chunk in page_two))

    def test_reference_to_appendix_in_body_is_not_treated_as_boundary(self) -> None:
        pages = [
            _page("제5조(적용기준)\n세부 기준을 정한다.", source="rules.pdf", page=0),
            _page("별표에 따른 기준을 모든 직원에게 적용한다.", source="rules.pdf", page=1),
        ]

        with patch.dict(os.environ, {"RAG_MIN_CHUNK_LENGTH": "1"}):
            chunks = build_chunks_from_pages(pages, chunk_size=1000, chunk_overlap=0)

        page_one = [chunk for chunk in chunks if chunk.metadata["page_index"] == 1]
        self.assertTrue(all(chunk.metadata["article"] == "제5조(적용기준)" for chunk in page_one))
        self.assertTrue(all(chunk.metadata["section_type"] == "main" for chunk in page_one))

    def test_table_rows_and_header_survive_chunking(self) -> None:
        page = _page(
            "[별표 1]\n"
            "구분    징계 기준    비고\n"
            "첫 번째 위반    견책-감봉    사고 없음\n"
            "두 번째 위반    정직-해임    사고 발생\n"
            "세 번째 위반    해임-파면    중대 사고",
            source="discipline.pdf",
            page=0,
        )

        with patch.dict(os.environ, {"RAG_MIN_CHUNK_LENGTH": "1"}):
            chunks = build_chunks_from_pages([page], chunk_size=55, chunk_overlap=0)

        row_chunks = [chunk for chunk in chunks if "위반" in chunk.page_content]
        self.assertGreaterEqual(len(row_chunks), 2)
        self.assertTrue(all("구분 | 징계 기준 | 비고" in chunk.page_content for chunk in row_chunks))
        self.assertTrue(any("[표 머리]" in chunk.page_content for chunk in row_chunks[1:]))
        combined = "\n".join(chunk.page_content for chunk in row_chunks)
        self.assertIn("견책-감봉", combined)
        self.assertIn("정직-해임", combined)
        self.assertIn("해임-파면", combined)


if __name__ == "__main__":
    unittest.main()
