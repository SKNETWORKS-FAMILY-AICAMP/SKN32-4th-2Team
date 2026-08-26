from __future__ import annotations

import unittest

from app.providers.base import Message
from app.providers.mock_provider import MockProvider


class MockProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_grounded_mock_answer_keeps_evidence_for_source_ui(self) -> None:
        provider = MockProvider("openai")
        result = await provider.generate(
            system="answer",
            messages=[
                Message(
                    role="user",
                    content="[참고 문서]\n[근거 E1]\n문서: 복무규정.pdf\n본문:\n내용",
                )
            ],
        )

        self.assertIn("[상태: ANSWER]", result.text)
        self.assertIn("[E1]", result.text)

    async def test_semantic_verifier_enum_is_supported_in_mock_mode(self) -> None:
        provider = MockProvider("openai")
        result = await provider.classify(
            system="verifier",
            user_content="content",
            allowed=("SUPPORTED", "UNSUPPORTED"),
        )

        self.assertEqual(result, "SUPPORTED")


if __name__ == "__main__":
    unittest.main()
