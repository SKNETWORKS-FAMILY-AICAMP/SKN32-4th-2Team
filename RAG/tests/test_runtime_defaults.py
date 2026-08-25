from __future__ import annotations

import inspect
import os
import unittest
from unittest.mock import patch

import torch

from config import Config
from rag_pipeline import _device, search_across_vector_stores


class DeviceSelectionTests(unittest.TestCase):
    def test_auto_uses_cpu_when_cuda_is_unavailable(self) -> None:
        with patch.dict(os.environ, {"RAG_DEVICE": "auto"}), patch(
            "torch.cuda.is_available", return_value=False
        ):
            self.assertEqual(_device(), "cpu")

    def test_auto_uses_cuda_when_available(self) -> None:
        with patch.dict(os.environ, {"RAG_DEVICE": "auto"}), patch(
            "torch.cuda.is_available", return_value=True
        ):
            self.assertEqual(_device(), "cuda")

    def test_explicit_cpu_overrides_cuda(self) -> None:
        with patch.dict(os.environ, {"RAG_DEVICE": "cpu"}), patch(
            "torch.cuda.is_available", return_value=True
        ):
            self.assertEqual(_device(), "cpu")

    def test_explicit_cuda_fails_clearly_when_unavailable(self) -> None:
        with patch.dict(os.environ, {"RAG_DEVICE": "cuda"}), patch(
            "torch.cuda.is_available", return_value=False
        ):
            with self.assertRaisesRegex(RuntimeError, "CUDA is not available"):
                _device()

    def test_invalid_device_is_rejected(self) -> None:
        with patch.dict(os.environ, {"RAG_DEVICE": "gpu"}):
            with self.assertRaisesRegex(ValueError, "RAG_DEVICE"):
                _device()


class RetrievalDefaultsTests(unittest.TestCase):
    def test_production_candidate_default_is_twenty(self) -> None:
        default = inspect.signature(search_across_vector_stores).parameters[
            "initial_candidates"
        ].default
        self.assertEqual(default, 20)
        self.assertEqual(Config.SEARCH_INITIAL_CANDIDATES, 20)


if __name__ == "__main__":
    unittest.main()
