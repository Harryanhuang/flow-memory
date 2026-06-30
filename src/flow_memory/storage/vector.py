"""Vector backend abstraction for Flow Memory.

Wraps LanceDB (default) with an ABC so alternative vector stores
can be plugged in.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path


class VectorBackend(ABC):
    """Abstract interface for vector storage."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether the underlying vector store is functional."""

    @abstractmethod
    def index(self, memory_id: str, content: str, metadata: dict) -> None:
        """Add or update a single memory in the index."""

    @abstractmethod
    def remove(self, memory_id: str) -> None:
        """Remove a memory from the index."""

    @abstractmethod
    def reindex_all(self, items: list[dict]) -> int:
        """Full rebuild: clear index and re-add all items.

        Each item dict has keys: id, content, scope, kind, layer,
        importance, status, updated_at.
        Returns count of indexed items.
        """

    @abstractmethod
    def search(
        self,
        query_text: str,
        top_k: int = 5,
        scope_filter: str | None = None,
        min_importance: int = 0,
    ) -> list[dict]:
        """Return list of {memory_id, content, score, scope, kind, ...}."""

    @abstractmethod
    def status(self) -> dict:
        """Return diagnostic dict {available, backend, dimension, row_count}."""


class LanceDBBackend(VectorBackend):
    """LanceDB-based vector backend (default).

    Requires `pip install flow-memory[vector]` (lancedb + sentence-transformers).
    All methods degrade gracefully when lancedb is unavailable.
    """

    def __init__(self, index_dir: Path | None = None) -> None:
        if index_dir is None:
            from flow_memory.storage.paths import get_path_provider
            index_dir = get_path_provider().vector_index_dir()
        self._index_dir = Path(index_dir)
        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._lancedb = None
        self._lancedb_db = None
        self._lancedb_available: bool | None = None
        self._table_name = "memory_items"

    def _ensure_lancedb(self):
        if self._lancedb_available is not None:
            return self._lancedb_available
        try:
            import lancedb

            self._lancedb = lancedb
            self._lancedb_available = True
        except ImportError:
            self._lancedb_available = False
        return self._lancedb_available

    def _get_db(self):
        if not self._ensure_lancedb():
            return None
        if self._lancedb_db is not None:
            return self._lancedb_db
        try:
            self._lancedb_db = self._lancedb.connect(str(self._index_dir))
        except Exception:
            return None
        return self._lancedb_db

    def _get_table(self):
        db = self._get_db()
        if db is None:
            return None
        try:
            return db.open_table(self._table_name)
        except Exception:
            return None

    def _encode(self, content: str):
        """Encode content to a vector using the configured embedding provider."""
        try:
            from flow_memory.embeddings import get_embedding_provider
            provider = get_embedding_provider()
            vector = provider.encode(content)
            if not any(v != 0.0 for v in vector):
                return None
            return vector
        except Exception:
            return None

    def is_available(self) -> bool:
        return self._ensure_lancedb()

    def index(self, memory_id: str, content: str, metadata: dict) -> None:
        if not self.is_available() or not content or not content.strip():
            return
        vector = self._encode(content)
        if vector is None:
            return
        row = {
            "memory_id": memory_id,
            "vector": vector,
            "content": content.strip()[:2000],
            "scope": metadata.get("scope", ""),
            "kind": metadata.get("kind", ""),
            "layer": metadata.get("layer", ""),
            "importance": int(metadata.get("importance", 5)),
            "status": metadata.get("status", "confirmed"),
            "updated_at": metadata.get("updated_at", ""),
        }
        try:
            db = self._get_db()
            if db is None:
                return
            table = self._get_table()
            if table is None:
                db.create_table(self._table_name, [row])
                return
            try:
                table.delete(f'memory_id = "{memory_id}"')
            except Exception:
                pass
            table.add([row])
        except Exception:
            pass

    def remove(self, memory_id: str) -> None:
        if not self.is_available():
            return
        try:
            table = self._get_table()
            if table is None:
                return
            table.delete(f'memory_id = "{memory_id}"')
        except Exception:
            pass

    def reindex_all(self, items: list[dict]) -> int:
        if not self.is_available():
            return 0
        try:
            db = self._get_db()
            if db is None:
                return 0
            try:
                db.drop_table(self._table_name)
            except Exception:
                pass

            rows = []
            for m in items:
                content = m.get("content", "")
                if not content or not content.strip():
                    continue
                vector = self._encode(content)
                if vector is None:
                    continue
                rows.append({
                    "memory_id": m.get("id", ""),
                    "vector": vector,
                    "content": content.strip()[:2000],
                    "scope": m.get("scope", ""),
                    "kind": m.get("kind", ""),
                    "layer": m.get("layer", ""),
                    "importance": int(m.get("importance", 5)),
                    "status": m.get("status", "confirmed"),
                    "updated_at": m.get("updated_at", ""),
                })
            if rows:
                db.create_table(self._table_name, rows)
            return len(rows)
        except Exception:
            return 0

    def search(
        self,
        query_text: str,
        top_k: int = 5,
        scope_filter: str | None = None,
        min_importance: int = 0,
    ) -> list[dict]:
        if not self.is_available() or not query_text or not query_text.strip():
            return []
        vector = self._encode(query_text)
        if vector is None:
            return []
        try:
            table = self._get_table()
            if table is None:
                return []
            try:
                results = table.search(vector).metric("cosine").limit(top_k * 2)
                df = results.to_pandas()
            except Exception:
                results = table.search(vector).limit(top_k * 2)
                df = results.to_pandas()

            if df.empty:
                return []

            out: list[dict] = []
            for _, row in df.iterrows():
                if scope_filter:
                    row_scope = row.get("scope", "")
                    if row_scope != scope_filter:
                        continue
                row_imp = int(row.get("importance", 0))
                if row_imp < min_importance:
                    continue
                out.append({
                    "memory_id": row.get("memory_id", ""),
                    "content": row.get("content", ""),
                    "score": float(row.get("_distance", 0.0)),
                    "scope": row.get("scope", ""),
                    "kind": row.get("kind", ""),
                    "layer": row.get("layer", ""),
                    "importance": row_imp,
                    "status": row.get("status", ""),
                })
                if len(out) >= top_k:
                    break
            return out
        except Exception:
            return []

    def status(self) -> dict:
        available = self.is_available()
        row_count = 0
        dimension = 0
        backend = "lancedb" if available else "none"
        if available:
            try:
                table = self._get_table()
                if table is not None:
                    row_count = table.count_rows()
                    import lancedb
                    if self._lancedb_db is not None:
                        dimension = self._lancedb_db.list_tables()
            except Exception:
                pass
        return {
            "available": available,
            "backend": backend,
            "dimension": dimension,
            "row_count": row_count,
            "index_dir": str(self._index_dir),
        }


# ── Module-level singleton ────────────────────────────────────────

_vector: VectorBackend | None = None


def get_vector_backend() -> VectorBackend:
    """Return the active vector backend. Lazy-inits LanceDBBackend."""
    global _vector
    if _vector is None:
        _vector = LanceDBBackend()
    return _vector


def use_vector_backend(backend: VectorBackend) -> None:
    """Replace the active vector backend."""
    global _vector
    _vector = backend