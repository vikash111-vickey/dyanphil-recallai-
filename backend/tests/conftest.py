"""Global pytest configuration and fixtures."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pytest

from app.config import settings
from app.main import API_COOKIE_NAME, get_api_token
from app.search.embedder import set_embedder
from starlette.testclient import TestClient

# Automatically seed session_token cookie on TestClient so existing tests pass
_orig_init = TestClient.__init__


def _patched_testclient_init(self, *args, **kwargs):
    _orig_init(self, *args, **kwargs)
    self.cookies.set(API_COOKIE_NAME, get_api_token())


TestClient.__init__ = _patched_testclient_init


class FakeEmbedder:
    """Deterministic, lightweight fake embedder with zero downloads for testing."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        dim: int = 16,
    ) -> None:
        self.model_name = model_name
        self.dim = dim

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)

        results = []
        for text in texts:
            vec = np.zeros(self.dim, dtype=np.float32)
            words = text.lower().split()
            if words:
                for word in words:
                    idx = abs(hash(word)) % self.dim
                    vec[idx] += 1.0
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                else:
                    vec[0] = 1.0
            else:
                vec[0] = 1.0
            results.append(vec)

        return np.array(results, dtype=np.float32)


@pytest.fixture(autouse=True)
def default_fake_embedder():
    """Ensure FakeEmbedder is active across all tests to prevent model downloads."""
    fake = FakeEmbedder(model_name=settings.embedding_model)
    set_embedder(fake)
    yield fake
    set_embedder(None)
