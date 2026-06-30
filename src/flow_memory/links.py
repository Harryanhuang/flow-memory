"""Memory Relationship Graph — directional links between memory items.

Supports six relation types: supports, contradicts, supersedes,
derived_from, explains, blocks.  Links form a directed graph that
enables reasoning about agreement, conflict, and provenance.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flow_memory.storage import get_backend

_VALID_RELATIONS = frozenset({
    "supports", "contradicts", "supersedes", "derived_from", "explains", "blocks",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_relation(relation: str) -> None:
    if relation not in _VALID_RELATIONS:
        raise ValueError(
            f"invalid relation: {relation!r} (valid: {sorted(_VALID_RELATIONS)})"
        )


def add_link(
    from_id: str,
    to_id: str,
    relation: str,
    *,
    created_at: str | None = None,
) -> None:
    """Create a directional link.  Idempotent (INSERT OR IGNORE)."""
    if not from_id.strip() or not to_id.strip():
        raise ValueError("from_id and to_id cannot be empty")
    _validate_relation(relation)
    get_backend().init_schema()
    now = created_at or _now_iso()
    conn = get_backend().connect()
    conn.execute(
        "INSERT OR IGNORE INTO memory_links (from_id, to_id, relation, created_at) "
        "VALUES (?, ?, ?, ?)",
        (from_id.strip(), to_id.strip(), relation, now),
    )
    conn.commit()


def remove_link(from_id: str, to_id: str, relation: str) -> bool:
    """Remove a specific link.  Returns True if a row was deleted."""
    _validate_relation(relation)
    get_backend().init_schema()
    conn = get_backend().connect()
    cur = conn.execute(
        "DELETE FROM memory_links WHERE from_id = ? AND to_id = ? AND relation = ?",
        (from_id.strip(), to_id.strip(), relation),
    )
    conn.commit()
    return cur.rowcount > 0


def get_links_from(memory_id: str) -> list[dict]:
    """All outgoing links from *memory_id*."""
    get_backend().init_schema()
    conn = get_backend().connect()
    rows = conn.execute(
        "SELECT * FROM memory_links WHERE from_id = ? ORDER BY relation, to_id",
        (memory_id.strip(),),
    ).fetchall()
    return [dict(r) for r in rows]


def get_links_to(memory_id: str) -> list[dict]:
    """All incoming links to *memory_id*."""
    get_backend().init_schema()
    conn = get_backend().connect()
    rows = conn.execute(
        "SELECT * FROM memory_links WHERE to_id = ? ORDER BY relation, from_id",
        (memory_id.strip(),),
    ).fetchall()
    return [dict(r) for r in rows]


def get_contradictions(memory_id: str) -> list[dict]:
    """Return all ``contradicts`` links in both directions for *memory_id*."""
    get_backend().init_schema()
    conn = get_backend().connect()
    rows = conn.execute(
        "SELECT * FROM memory_links "
        "WHERE relation = 'contradicts' AND (from_id = ? OR to_id = ?) "
        "ORDER BY from_id, to_id",
        (memory_id.strip(), memory_id.strip()),
    ).fetchall()
    return [dict(r) for r in rows]


def get_support_chain(memory_id: str, *, max_depth: int = 3) -> list[dict]:
    """Recursively follow ``supports`` and ``derived_from`` links from
    *memory_id*, returning the transitive chain (up to *max_depth* hops).
    Includes a ``_depth`` field on each result dict.

    Cycle-safe: each memory ID is visited at most once.
    """
    get_backend().init_schema()
    conn = get_backend().connect()
    visited: set[str] = set()
    result: list[dict] = []
    frontier = [(memory_id.strip(), 0)]

    while frontier:
        mid, depth = frontier.pop(0)
        if mid in visited or depth > max_depth:
            continue
        visited.add(mid)
        rows = conn.execute(
            "SELECT * FROM memory_links "
            "WHERE from_id = ? AND relation IN ('supports', 'derived_from') "
            "ORDER BY relation, to_id",
            (mid,),
        ).fetchall()
        for r in rows:
            entry = dict(r)
            entry["_depth"] = depth + 1
            result.append(entry)
            frontier.append((r["to_id"], depth + 1))

    return result


def get_all_links() -> list[dict]:
    """Return every link in the table (for audit/export)."""
    get_backend().init_schema()
    conn = get_backend().connect()
    rows = conn.execute(
        "SELECT * FROM memory_links ORDER BY from_id, to_id, relation"
    ).fetchall()
    return [dict(r) for r in rows]
