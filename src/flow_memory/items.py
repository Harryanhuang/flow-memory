"""Memory Items CRUD and query.

Long-term knowledge assets stored in SQLite. Each item has:
  layer (core|task|episode|decision|reflection|archive)
  scope (team|lane:X|agent:X|workflow:X|task:X|subject:X|project:X)
  kind (role_rule|workflow_rule|decision|mistake|preference|handoff|domain_fact|runtime_rule|note)
  status (candidate|confirmed|deprecated|rejected)

Supports supersession (complete replacement) and revision_of (minor update with audit trail).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flow_memory.storage import get_backend

_VALID_LAYERS = frozenset({"core", "task", "episode", "decision", "reflection", "archive"})
_VALID_KINDS = frozenset({
    "role_rule", "workflow_rule", "decision", "mistake", "preference",
    "handoff", "domain_fact", "runtime_rule", "note",
})
_VALID_ITEM_STATUSES = frozenset({"candidate", "confirmed", "deprecated", "rejected"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_id(now: str) -> str:
    date_part = now[:10].replace("-", "")
    prefix = f"MI-{date_part}-"
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(id, ?) AS INTEGER)) FROM memory_items WHERE id LIKE ?",
        (len(prefix) + 1, f"{prefix}%"),
    ).fetchone()
    seq = (row[0] or 0) + 1
    return f"MI-{date_part}-{seq:03d}"


def add_memory(
    scope: str,
    kind: str,
    content: str,
    *,
    layer: str = "episode",
    summary: str = "",
    source_ref: str = "",
    evidence_refs: list[str] | None = None,
    confidence: float = 1.0,
    importance: int = 5,
    valid_until: str = "",
    created_by: str = "",
    supersedes: str = "",
    revision_of: str = "",
    status: str = "candidate",
    metadata: dict | None = None,
) -> str:
    """Add a new memory item. Returns the memory ID."""
    if kind not in _VALID_KINDS:
        raise ValueError(f"invalid kind: {kind} (valid: {sorted(_VALID_KINDS)})")
    if layer not in _VALID_LAYERS:
        raise ValueError(f"invalid layer: {layer} (valid: {sorted(_VALID_LAYERS)})")
    if status not in _VALID_ITEM_STATUSES:
        raise ValueError(f"invalid status: {status} (valid: {sorted(_VALID_ITEM_STATUSES)})")
    if not content.strip():
        raise ValueError("content cannot be empty")
    if not 1 <= importance <= 10:
        raise ValueError(f"importance must be 1-10, got {importance}")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be 0.0-1.0, got {confidence}")

    get_backend().init_schema()
    now = _now_iso()
    mid = _next_id(now)
    conn = get_backend().connect()
    conn.execute(
        """INSERT INTO memory_items
           (id, layer, scope, kind, status, content, summary, source_ref,
            evidence_refs, confidence, importance, valid_from, valid_until,
            created_by, created_at, updated_at, supersedes, revision_of,
            metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            mid, layer, scope, kind, status, content.strip(), summary,
            source_ref, json.dumps(evidence_refs or []),
            confidence, importance,
            now, valid_until, created_by, now, now,
            supersedes, revision_of,
            json.dumps(metadata or {}),
        ),
    )
    conn.commit()
    # Sync FTS index
    try:
        from eduflow.memory.search import sync_fts
        sync_fts(mid, content.strip(), summary)
    except Exception:
        pass  # best-effort: FTS sync failure should not block inserts
    # Sync vector index (best-effort)
    if status == "confirmed":
        try:
            from eduflow.memory.vector_store import index_memory
            index_memory(
                mid,
                content.strip(),
                {
                    "scope": scope,
                    "kind": kind,
                    "layer": layer,
                    "importance": importance,
                    "status": status,
                    "updated_at": now,
                },
            )
        except Exception:
            pass
    return mid


def get_memory(memory_id: str) -> dict | None:
    """Fetch a single memory item by ID."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT * FROM memory_items WHERE id = ?", (memory_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    # Legacy rows may not have pinned column; default to 0
    d.setdefault("pinned", 0)
    return d


def list_pinned_memories(scope: str | list[str] | None = None, limit: int = 50) -> list[dict]:
    """List pinned memory items. Pinned items are protected from budget eviction."""
    get_backend().init_schema()
    conn = get_backend().connect()
    query = (
        "SELECT * FROM memory_items WHERE status='confirmed' "
        "AND COALESCE(pinned, 0) = 1"
    )
    params: list = []
    if scope is not None:
        if isinstance(scope, str):
            query += " AND scope = ?"
            params.append(scope)
        elif isinstance(scope, list) and scope:
            placeholders = ", ".join("?" for _ in scope)
            query += f" AND scope IN ({placeholders})"
            params.extend(scope)
    query += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    results = [dict(r) for r in rows]
    for r in results:
        r.setdefault("pinned", 1)
    return results


def pin_memory(memory_id: str) -> bool:
    """Mark a memory as pinned. Returns True if state changed."""
    get_backend().init_schema()
    conn = get_backend().connect()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "UPDATE memory_items SET pinned = 1, updated_at = ? WHERE id = ? "
        "AND COALESCE(pinned, 0) = 0",
        (now, memory_id),
    )
    conn.commit()
    return cur.rowcount > 0


def unpin_memory(memory_id: str) -> bool:
    """Remove pin from a memory. Returns True if state changed."""
    get_backend().init_schema()
    conn = get_backend().connect()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "UPDATE memory_items SET pinned = 0, updated_at = ? WHERE id = ? "
        "AND COALESCE(pinned, 0) = 1",
        (now, memory_id),
    )
    conn.commit()
    return cur.rowcount > 0


def list_memories(
    *,
    scope: str | None = None,
    kind: str | None = None,
    status: str = "confirmed",
    layer: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List memory items with optional filters. Default status='confirmed'."""
    get_backend().init_schema()
    conn = get_backend().connect()
    query = "SELECT * FROM memory_items WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if scope:
        query += " AND scope = ?"
        params.append(scope)
    if kind:
        query += " AND kind = ?"
        params.append(kind)
    if layer:
        query += " AND layer = ?"
        params.append(layer)
    query += " ORDER BY importance DESC, created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def deprecate_memory(memory_id: str, *, reason: str = "") -> bool:
    """Mark a memory as deprecated. Returns True if found and changed."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT status FROM memory_items WHERE id = ?",
        (memory_id,),
    ).fetchone()
    if row is None:
        return False
    if row["status"] == "deprecated":
        return False
    now = _now_iso()
    conn.execute(
        "UPDATE memory_items SET status = 'deprecated', updated_at = ? WHERE id = ?",
        (now, memory_id),
    )
    conn.commit()
    # Sync vector index (best-effort removal)
    try:
        from eduflow.memory.vector_store import remove_from_index
        remove_from_index(memory_id)
    except Exception:
        pass
    return True


def supersede_memory(old_id: str, new_id: str) -> bool:
    """Deprecate old_id and set new_id.supersedes=old_id. Returns True if changed."""
    get_backend().init_schema()
    conn = get_backend().connect()
    old_row = conn.execute(
        "SELECT status FROM memory_items WHERE id = ?", (old_id,)
    ).fetchone()
    if old_row is None:
        return False
    new_row = conn.execute(
        "SELECT id FROM memory_items WHERE id = ?", (new_id,)
    ).fetchone()
    if new_row is None:
        return False
    now = _now_iso()
    conn.execute(
        "UPDATE memory_items SET status = 'deprecated', updated_at = ? WHERE id = ?",
        (now, old_id),
    )
    conn.execute(
        "UPDATE memory_items SET supersedes = ?, updated_at = ? WHERE id = ?",
        (old_id, now, new_id),
    )
    conn.commit()
    # Sync vector index: remove old vector (best-effort)
    try:
        from eduflow.memory.vector_store import remove_from_index
        remove_from_index(old_id)
    except Exception:
        pass
    return True


def update_memory(memory_id: str, **fields) -> bool:
    """Update allowed fields on a memory item. Returns True if found."""
    allowed = {
        "content", "summary", "source_ref", "evidence_refs",
        "confidence", "importance", "valid_until", "layer",
        "kind", "status", "metadata_json",
    }
    invalid = set(fields) - allowed
    if invalid:
        raise ValueError(f"cannot update fields: {sorted(invalid)}")
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT id FROM memory_items WHERE id = ?", (memory_id,)
    ).fetchone()
    if row is None:
        return False
    now = _now_iso()
    sets = ["updated_at = ?"]
    params: list = [now]
    for k, v in fields.items():
        if k == "evidence_refs" and isinstance(v, list):
            v = json.dumps(v)
        elif k == "metadata_json" and isinstance(v, dict):
            v = json.dumps(v)
        sets.append(f"{k} = ?")
        params.append(v)
    params.append(memory_id)
    conn.execute(
        f"UPDATE memory_items SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    conn.commit()
    # Sync FTS index with updated content
    try:
        from eduflow.memory.search import sync_fts
        updated = get_memory(memory_id)
        if updated:
            sync_fts(memory_id, updated.get("content", ""), updated.get("summary", ""))
    except Exception:
        pass
    # Sync vector index (best-effort)
    try:
        from eduflow.memory.vector_store import index_memory
        updated = get_memory(memory_id)
        if updated and updated.get("status") == "confirmed":
            index_memory(
                memory_id,
                updated.get("content", ""),
                {
                    "scope": updated.get("scope", ""),
                    "kind": updated.get("kind", ""),
                    "layer": updated.get("layer", ""),
                    "importance": updated.get("importance", 5),
                    "status": updated.get("status", ""),
                    "updated_at": updated.get("updated_at", now),
                },
            )
    except Exception:
        pass
    return True
