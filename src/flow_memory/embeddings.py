"""Embedding providers for Flow Memory vector search.

Currently supports:
  - SiliconFlowEmbeddingProvider (Qwen3-VL-Embedding-8B, dim=4096) — production
  - DummyProvider — fallback when no API key is configured

Future: OpenAI, Cohere, local sentence-transformers (via the [vector] extra).
"""
from __future__ import annotations

import hashlib
import logging
import os

_log = logging.getLogger(__name__)


class EmbeddingProvider:
    """Abstract base for embedding providers."""

    backend: str = "abstract"
    dimension: int = 0

    def encode(self, text: str) -> list[float]:
        """Encode a single text into a vector."""
        raise NotImplementedError

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts."""
        return [self.encode(t) for t in texts]


class SiliconFlowEmbeddingProvider(EmbeddingProvider):
    """SiliconFlow-hosted Qwen3-VL-Embedding-8B model (dim=4096)."""

    backend = "siliconflow"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        api_base: str | None = None,
        timeout: int = 30,
        batch_size: int = 32,
        dimension: int = 4096,
    ) -> None:
        self.api_key = api_key or os.environ.get(
            "FLOW_MEMORY_EMBEDDING_API_KEY",
            os.environ.get("EDUFLOW_EMBEDDING_API_KEY", ""),
        )
        self.model = model or os.environ.get(
            "FLOW_MEMORY_EMBEDDING_MODEL",
            "Qwen/Qwen3-VL-Embedding-8B",
        )
        self.api_base = api_base or os.environ.get(
            "FLOW_MEMORY_EMBEDDING_BASE",
            "https://api.siliconflow.cn/v1",
        )
        self.timeout = timeout
        self.batch_size = batch_size
        self._dimension = int(
            os.environ.get("FLOW_MEMORY_EMBEDDING_DIM", str(dimension))
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    def encode(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * self._dimension
        if not self.api_key:
            raise RuntimeError("No API key for SiliconFlowEmbeddingProvider")

        try:
            import urllib.request
            import json as _json

            url = f"{self.api_base}/embeddings"
            payload = _json.dumps({
                "model": self.model,
                "input": text,
                "encoding_format": "float",
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
                emb = data["data"][0]["embedding"]
                if len(emb) != self._dimension:
                    self._dimension = len(emb)
                return emb
        except Exception as exc:
            _log.debug("SiliconFlow embedding failed: %s", exc)
            return [0.0] * self._dimension

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]


class DummyProvider(EmbeddingProvider):
    """Deterministic zero-vector provider for tests and offline use."""

    backend = "dummy"
    dimension = 4096

    def encode(self, text: str) -> list[float]:
        if not text:
            return [0.0] * self.dimension
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vec: list[float] = []
        for i in range(0, len(digest), 4):
            chunk = digest[i : i + 4]
            val = int.from_bytes(chunk, "big", signed=False) / 2**32
            vec.append(val)
        while len(vec) < self.dimension:
            vec.append(0.0)
        return vec[: self.dimension]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.encode(t) for t in texts]


# ── Module-level singleton ────────────────────────────────────────

_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return the active embedding provider. Lazy-inits based on env."""
    global _provider
    if _provider is None:
        api_key = os.environ.get("FLOW_MEMORY_EMBEDDING_API_KEY") or os.environ.get(
            "EDUFLOW_EMBEDDING_API_KEY", ""
        )
        if api_key.strip():
            _provider = SiliconFlowEmbeddingProvider(api_key=api_key)
        else:
            _log.debug("No API key; using DummyProvider")
            _provider = DummyProvider()
    return _provider


def set_embedding_provider(provider: EmbeddingProvider) -> None:
    """Replace the active embedding provider."""
    global _provider
    _provider = provider


def reset_embedding_provider() -> None:
    """Reset the cached provider (useful in tests)."""
    global _provider
    _provider = None