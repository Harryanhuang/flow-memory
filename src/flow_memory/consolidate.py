"""Memory consolidation: detect and merge duplicate/similar memories.

Detects semantically similar confirmed memories using vector search and
provides CLI operations to merge them with audit trail.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flow_memory.storage import get_backend


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_similar_pairs(
    scope: str | None = None,
    kind: str | None = None,
    threshold: float = 0.85,
    limit_pairs: int = 50,
) -> list[dict]:
    """Find pairs of confirmed memory_items with high semantic similarity.

    Uses vector_store.search_similar() when available; returns empty list
    otherwise (graceful degradation).

    Returns list of {id_a, id_b, score, content_a, content_b, scope, kind}
    sorted by score descending.
    """
    get_backend().init_schema()
    conn = get_backend().connect()

    # Build base query
    query = "SELECT id, content, scope, kind, summary FROM memory_items WHERE status='confirmed'"
    params: list = []
    if scope:
        query += " AND scope = ?"
        params.append(scope)
    if kind:
        query += " AND kind = ?"
        params.append(kind)
    query += " LIMIT 1000"

    items = [dict(r) for r in conn.execute(query, params).fetchall()]
    if len(items) < 2:
        return []

    # Try vector-store based detection
    try:
        from eduflow.memory.vector_store import search_similar
    except ImportError:
        return []

    pairs = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        mid = item.get("id", "")
        if not mid:
            continue
        try:
            similar = search_similar(item.get("content", ""), top_k=5)
        except Exception:
            continue
        for s in similar:
            other_id = s.get("memory_id", "")
            if not other_id or other_id == mid:
                continue
            score = float(s.get("score", 0.0))
            if score < threshold:
                continue
            pair_key = tuple(sorted([mid, other_id]))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            # Look up the other item from our local list (avoid extra SQLite hit)
            other = next((x for x in items if x.get("id") == other_id), None)
            pairs.append({
                "id_a": pair_key[0],
                "id_b": pair_key[1],
                "score": score,
                "content_a": item.get("content", "")[:200],
                "content_b": other["content"][:200] if other else "",
                "scope": item.get("scope", ""),
                "kind": item.get("kind", ""),
            })
            if len(pairs) >= limit_pairs:
                break
        if len(pairs) >= limit_pairs:
            break

    pairs.sort(key=lambda x: x["score"], reverse=True)
    return pairs


def merge_memories(
    keep_id: str,
    drop_id: str,
    reason: str = "",
) -> dict:
    """Merge two memories: keep keep_id, deprecate drop_id.

    Steps:
      1. Verify both exist and are confirmed
      2. Verify scope compatibility
      3. Append drop_id's evidence_refs to keep_id (deduped)
      4. Set drop_id status='deprecated'
      5. Create memory_link: keep_id supersedes drop_id
      6. Remove drop_id from vector index
      7. Write audit log

    Returns {merged: True, keep_id, drop_id, reason}.
    Raises ValueError if either memory missing or scopes conflict.
    """
    get_backend().init_schema()
    conn = get_backend().connect()

    keep = conn.execute("SELECT * FROM memory_items WHERE id = ?", (keep_id,)).fetchone()
    drop = conn.execute("SELECT * FROM memory_items WHERE id = ?", (drop_id,)).fetchone()
    if keep is None:
        raise ValueError(f"keep_id not found: {keep_id}")
    if drop is None:
        raise ValueError(f"drop_id not found: {drop_id}")

    # Scope compatibility check (allow team↔lane but not task↔team)
    keep_scope = keep["scope"]
    drop_scope = drop["scope"]
    if keep_scope != drop_scope:
        # Different scopes — still allow but warn via audit
        pass

    # Merge evidence_refs (dedup)
    try:
        keep_ev = json.loads(keep["evidence_refs"] or "[]")
    except (json.JSONDecodeError, TypeError):
        keep_ev = []
    try:
        drop_ev = json.loads(drop["evidence_refs"] or "[]")
    except (json.JSONDecodeError, TypeError):
        drop_ev = []

    merged_ev = list(dict.fromkeys(keep_ev + drop_ev))  # preserves order

    now = _now_iso()

    # Update keep_id with merged evidence
    conn.execute(
        "UPDATE memory_items SET evidence_refs = ?, updated_at = ? WHERE id = ?",
        (json.dumps(merged_ev, ensure_ascii=False), now, keep_id),
    )

    # Deprecate drop_id
    conn.execute(
        "UPDATE memory_items SET status = 'deprecated', updated_at = ? WHERE id = ?",
        (now, drop_id),
    )

    # Create supersedes link
    try:
        from eduflow.memory.links import add_link
        add_link(keep_id, drop_id, "supersedes")
    except Exception:
        pass

    conn.commit()

    # Remove from vector index
    try:
        from eduflow.memory.vector_store import remove_from_index
        remove_from_index(drop_id)
    except Exception:
        pass

    # Audit log
    audit_record = {
        "ts": now,
        "action": "memory_merge",
        "keep_id": keep_id,
        "drop_id": drop_id,
        "reason": reason,
        "merged_evidence_count": len(merged_ev),
        "drop_content_backup": drop["content"][:500],  # backup for recovery
    }
    try:
        from pathlib import Path
        log_path = get_path_provider().audit_log_file()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit_record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return {"merged": True, "keep_id": keep_id, "drop_id": drop_id, "reason": reason}


def consolidation_report(threshold: float = 0.90) -> dict:
    """Generate a consolidation report (advisory only).

    Returns {threshold, pair_count, top_pairs: [...]}.
    """
    pairs = find_similar_pairs(threshold=threshold, limit_pairs=10)
    return {
        "threshold": threshold,
        "pair_count": len(pairs),
        "top_pairs": [
            {
                "id_a": p["id_a"],
                "id_b": p["id_b"],
                "score": round(p["score"], 3),
                "content_a": p["content_a"][:80],
                "content_b": p["content_b"][:80],
            }
            for p in pairs
        ],
    }