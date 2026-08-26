from __future__ import annotations

import unittest

from app import prompts
from bench import variants


class BenchVariantTests(unittest.TestCase):
    def test_rule3_variant_tracks_numbered_rule_boundaries(self) -> None:
        replacement = "3. 실험용 출처 규칙입니다."

        changed = variants._swap_rule3(prompts.ANSWER_SYSTEM, replacement)

        self.assertIn(replacement, changed)
        self.assertEqual(changed.count(replacement), 1)
        self.assertIn("\n4. 한국어 존댓말로", changed)
        self.assertNotIn("3. 각 참고 문서는", changed)


if __name__ == "__main__":
    unittest.main()
