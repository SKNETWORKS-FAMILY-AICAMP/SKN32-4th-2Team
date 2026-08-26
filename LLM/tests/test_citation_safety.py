from __future__ import annotations

import unittest

from app.services.answer import strip_unverifiable_citations


class CitationSafetyTests(unittest.TestCase):
    def test_disabled_citations_remove_ocr_spacing_variants(self) -> None:
        cleaned = strip_unverifiable_citations(
            "근로기준법 제 50 조 의 2에 따라 처리합니다.",
            "제50조의2",
            allow=False,
        )

        self.assertNotIn("제 50 조", cleaned)
        self.assertEqual(cleaned, "근로기준법에 따라 처리합니다.")


if __name__ == "__main__":
    unittest.main()
