"""FTS5 full-text search for memory items.

Lazily creates the FTS5 virtual table when available, falls back to LIKE
on memory_items.content/summary when FTS5 is not compiled in.
"""
from __future__ import annotations

import sqlite3

from flow_memory.storage import get_backend

_FTS_AVAILABLE: bool | None = None


def _check_fts5() -> bool:
    """Test if FTS5 is compiled into this SQLite build."""
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE _test_fts USING fts5(content)")
        conn.execute("DROP TABLE _test_fts")
        conn.close()
        return True
    except Exception:
        return False


def _fts_available() -> bool:
    global _FTS_AVAILABLE
    if _FTS_AVAILABLE is None:
        _FTS_AVAILABLE = _check_fts5()
    return _FTS_AVAILABLE


def ensure_fts() -> None:
    """Create FTS5 virtual table if available. No-op if unavailable."""
    if not _fts_available():
        return
    conn = get_backend().connect()
    try:
        conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts
               USING fts5(content, summary, id UNINDEXED,
                          tokenize='trigram')"""
        )
        conn.commit()
    except Exception:
        pass  # table may already exist or FTS5 unavailable at runtime


def sync_fts(memory_id: str, content: str, summary: str) -> None:
    """Insert/update FTS index for a memory item."""
    if not _fts_available():
        return
    ensure_fts()
    conn = get_backend().connect()
    # Remove existing entry first (idempotent upsert)
    conn.execute(
        "DELETE FROM memory_items_fts WHERE id = ?", (memory_id,)
    )
    conn.execute(
        "INSERT INTO memory_items_fts (id, content, summary) VALUES (?, ?, ?)",
        (memory_id, content, summary),
    )
    conn.commit()


def remove_fts(memory_id: str) -> None:
    """Remove FTS index for a memory item."""
    if not _fts_available():
        return
    conn = get_backend().connect()
    try:
        conn.execute(
            "DELETE FROM memory_items_fts WHERE id = ?", (memory_id,)
        )
        conn.commit()
    except Exception:
        pass  # table may not exist


def search_memories(
    query: str,
    *,
    scope: str | None = None,
    kind: str | None = None,
    status: str = "confirmed",
    limit: int = 20,
) -> list[dict]:
    """Full-text search with LIKE fallback.

    Returns memory_items rows matching the query, ordered by rank.
    """
    if not query or not query.strip():
        return []

    get_backend().init_schema()
    conn = get_backend().connect()
    q = query.strip()
    use_fts = _fts_available()

    if use_fts:
        ensure_fts()
        base = (
            "SELECT m.* FROM memory_items m"
            " JOIN memory_items_fts f ON m.id = f.id"
            " WHERE memory_items_fts MATCH ?"
        )
        params: list = [f'"{q}"']
    else:
        base = (
            "SELECT * FROM memory_items"
            " WHERE (content LIKE ? OR summary LIKE ?)"
        )
        like_pat = f"%{q}%"
        params = [like_pat, like_pat]

    if status:
        base += " AND status = ?" if not use_fts else " AND m.status = ?"
        params.append(status)
    if scope:
        base += " AND scope = ?" if not use_fts else " AND m.scope = ?"
        params.append(scope)
    if kind:
        base += " AND kind = ?" if not use_fts else " AND m.kind = ?"
        params.append(kind)

    base += " LIMIT ?"
    params.append(limit)

    rows = conn.execute(base, params).fetchall()
    return [dict(r) for r in rows]


def hybrid_search(
    query: str,
    *,
    scope: str | list[str] | None = None,
    kind: str | None = None,
    status: str = "confirmed",
    limit: int = 20,
    fts_top_k: int | None = None,
    vector_top_k: int | None = None,
    rrf_k: int = 60,
) -> list[dict]:
    """Hybrid search: FTS5 + Vector fusion via Reciprocal Rank Fusion (RRF).

    Algorithm:
      1. Query FTS5 -> ranked list A
      2. Query vector_store -> ranked list B
      3. RRF score = sum(1 / (rrf_k + rank_i)) for each source i
      4. Merge by memory_id, sort by RRF score desc
      5. Hydrate from SQLite and return with _sources annotation

    Returns list of memory dicts with extra "_sources" field: {"fts", "vec", "fts+vec"}.
    Falls back to FTS-only when vector store unavailable or returns empty.
    """
    if not query or not query.strip():
        return []

    fts_top_k = fts_top_k or (limit * 2)
    vector_top_k = vector_top_k or (limit * 2)

    # FTS pass
    fts_results = search_memories(
        query, scope=scope, kind=kind, status=status, limit=fts_top_k
    )

    # Vector pass (best-effort)
    vec_results = []
    try:
        from eduflow.memory.vector_store import search_similar
        vec_results = search_similar(query, top_k=vector_top_k)
    except Exception:
        vec_results = []

    # RRF fusion
    rrf_scores: dict[str, float] = {}
    sources: dict[str, set[str]] = {}

    for rank, m in enumerate(fts_results, start=1):
        mid = m.get("id", "")
        if not mid:
            continue
        rrf_scores[mid] = rrf_scores.get(mid, 0.0) + 1.0 / (rrf_k + rank)
        sources.setdefault(mid, set()).add("fts")

    for rank, m in enumerate(vec_results, start=1):
        mid = m.get("memory_id", "")
        if not mid:
            continue
        rrf_scores[mid] = rrf_scores.get(mid, 0.0) + 1.0 / (rrf_k + rank)
        sources.setdefault(mid, set()).add("vec")

    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

    from eduflow.memory.items import get_memory as _get_memory
    hydrated: list[dict] = []
    for mid in sorted_ids[:limit]:
        row = _get_memory(mid)
        if row is None:
            continue
        srcs = sources.get(mid, set())
        if "fts" in srcs and "vec" in srcs:
            row["_sources"] = "fts+vec"
        elif "fts" in srcs:
            row["_sources"] = "fts"
        else:
            row["_sources"] = "vec"
        row["_rrf_score"] = rrf_scores[mid]
        hydrated.append(row)

    return hydrated
