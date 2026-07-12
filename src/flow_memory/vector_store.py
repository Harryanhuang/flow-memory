"""Vector store for Flow Memory.

Backwards-compat module that re-exports from the new abstraction layer.
"""

from __future__ import annotations

from flow_memory.storage.vector import (
    get_vector_backend,
)


def index_memory(memory_id: str, content: str, metadata: dict) -> None:
    """Add or update a memory in the vector index."""
    get_vector_backend().index(memory_id, content, metadata)


def remove_from_index(memory_id: str) -> None:
    """Remove a memory from the vector index."""
    get_vector_backend().remove(memory_id)


def search_similar(
    query_text: str,
    top_k: int = 5,
    scope_filter: str | None = None,
    min_importance: int = 0,
) -> list[dict]:
    """Semantic similarity search."""
    return get_vector_backend().search(
        query_text,
        top_k=top_k,
        scope_filter=scope_filter,
        min_importance=min_importance,
    )


def index_all_confirmed() -> int:
    """Full rebuild of the vector index from all confirmed memories."""
    from flow_memory.storage import get_backend

    conn = get_backend().connect()
    rows = conn.execute(
        "SELECT id, content, scope, kind, layer, importance, status, updated_at "
        "FROM memory_items WHERE status='confirmed'"
    ).fetchall()
    items = [dict(r) for r in rows]
    return get_vector_backend().reindex_all(items)


def index_status() -> dict:
    """Return diagnostic dict for the vector index."""
    return get_vector_backend().status()
