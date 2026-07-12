"""Automatic expiry for EduFlow Memory rows.

Periodically run to transition expired rows to their terminal states:
  - active_constraints with past valid_until → inactive
  - memory_items (confirmed) with past valid_until → deprecated
  - memory_candidates (proposed) with past expires_at → rejected

All functions are idempotent: second call returns 0.
"""

from __future__ import annotations

from datetime import datetime, timezone

from flow_memory.storage import get_backend
from flow_memory import candidates as _candidates


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def expire_constraints() -> int:
    """Mark active constraints with past valid_until as inactive.

    Returns count of constraints transitioned. Empty valid_until means
    no expiry — those rows are left alone.
    """
    get_backend().init_schema()
    conn = get_backend().connect()
    now = _now_iso()
    try:
        cursor = conn.execute(
            "UPDATE active_constraints "
            "SET status = 'inactive', updated_at = ? "
            "WHERE status = 'active' AND valid_until != '' AND SUBSTR(valid_until, 1, 19) <= ?",
            (now, now),
        )
        conn.commit()
        return cursor.rowcount
    except Exception:
        return 0


def expire_memories() -> int:
    """Mark confirmed memories with past valid_until as deprecated.

    Returns count of memories transitioned. Only 'confirmed' rows are
    touched — candidate/deprecated rows are already handled elsewhere.
    """
    get_backend().init_schema()
    conn = get_backend().connect()
    now = _now_iso()
    try:
        cursor = conn.execute(
            "UPDATE memory_items "
            "SET status = 'deprecated', updated_at = ? "
            "WHERE status = 'confirmed' AND valid_until != '' AND SUBSTR(valid_until, 1, 19) <= ?",
            (now, now),
        )
        conn.commit()
        return cursor.rowcount
    except Exception:
        return 0


def expire_candidates() -> int:
    """Delegate to candidates.expire_stale_candidates().

    Marks proposed candidates past their expires_at as rejected with
    reviewed_by='system'.
    """
    try:
        return _candidates.expire_stale_candidates()
    except Exception:
        return 0


def run_all_expirations() -> dict:
    """Run all three expiration scans and return a summary.

    Returns {constraints_expired, memories_expired, candidates_expired, total}.
    """
    c = expire_constraints()
    m = expire_memories()
    cand = expire_candidates()
    return {
        "constraints_expired": c,
        "memories_expired": m,
        "candidates_expired": cand,
        "total": c + m + cand,
    }
