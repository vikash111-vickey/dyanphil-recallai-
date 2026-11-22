"""Embedding module using fastembed (ONNX runtime) with normalized vectors."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

import numpy as np

from app.config import settings


class Embedder:
    """Lazy-loaded FastEmbed embedding provider with cosine normalization."""

    def __init__(
        self,
        model_name: str | None = None,
        cache_dir: Path | str | None = None,
    ) -> None:
        self.model_name = model_name or settings.embedding_model
        self.cache_dir = Path(cache_dir or settings.fastembed_cache_path)
        self._model = None

    def _ensure_model_loaded(self) -> None:
        if self._model is None:
            from fastembed import TextEmbedding

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            # Ensure environment variable is set as well
            os.environ["FASTEMBED_CACHE_PATH"] = str(self.cache_dir)
            self._model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=str(self.cache_dir),
            )

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        """
        Embed a list of text strings into a 2D float32 numpy array.
        Vectors are L2-normalized for direct cosine similarity via dot product.
        """
        if not texts:
            return np.empty((0, 384), dtype=np.float32)

        self._ensure_model_loaded()
        embeddings_gen = self._model.embed(list(texts))
        vectors = np.array(list(embeddings_gen), dtype=np.float32)

        # L2-normalize vectors for cosine similarity
        norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
        norms = np.maximum(norms, 1e-12)
        normalized = vectors / norms
        return normalized.astype(np.float32)


# Global singleton instance loaded once lazily
_default_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """Retrieve or create the global Embedder instance."""
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = Embedder()
    return _default_embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Set or override the global embedder instance (useful for tests)."""
    global _default_embedder
    _default_embedder = embedder
