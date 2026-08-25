from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.config import Settings
from app.domain import FALLBACK_TOPIC
from app.services.naming import fallback_name, generate_name
from app.services.topic import classify


class _SlowProvider:
    name = "slow"

    async def generate(self, **_kwargs):
        await asyncio.sleep(1)

    async def classify(self, **_kwargs):
        await asyncio.sleep(1)


class RuntimeTimeoutTests(unittest.IsolatedAsyncioTestCase):
    def test_default_llm_timeout_is_fifteen_seconds(self) -> None:
        self.assertEqual(Settings.model_fields["llm_timeout_sec"].default, 15.0)

    def test_default_rag_timeout_matches_cpu_safe_deployment(self) -> None:
        self.assertEqual(Settings.model_fields["rag_timeout_sec"].default, 45.0)

    async def test_naming_timeout_returns_fallback(self) -> None:
        message = "연차 사용 방법을 알려주세요"
        with patch(
            "app.services.naming.get_provider", return_value=_SlowProvider()
        ), patch(
            "app.services.naming.get_settings",
            return_value=SimpleNamespace(llm_timeout_sec=0.001),
        ):
            self.assertEqual(await generate_name(message), fallback_name(message))

    async def test_topic_timeout_returns_fallback(self) -> None:
        with patch(
            "app.services.topic.get_provider", return_value=_SlowProvider()
        ), patch(
            "app.services.topic.get_settings",
            return_value=SimpleNamespace(llm_timeout_sec=0.001),
        ):
            topic, cached = await classify("연차 질문", use_cache=False)
        self.assertEqual(topic, FALLBACK_TOPIC)
        self.assertFalse(cached)


if __name__ == "__main__":
    unittest.main()
