"""Storage budget enforcement for EduFlow Memory tables.

Prevents unbounded DB growth by tracking row counts against configurable
limits and evicting the least valuable rows when over budget.

Eviction priority (first evicted first):
  active_constraints: deprecated → inactive → active
  memory_items:       deprecated → rejected → candidate → confirmed
  memory_candidates:  rejected → proposed → promoted
"""
from __future__ import annotations

import os
from pathlib import Path

from flow_memory.storage import get_backend
from flow_memory.storage.paths import get_path_provider

# ── limits ─────────────────────────────────────────────────────────

LIMITS: dict[str, int] = {
    "active_constraints": 50,
    "memory_items": 500,
    "memory_candidates": 200,
}
_MIN_KEEP = 1

# Status → priority (lower = evict first). Unknown statuses get 99.
_STATUS_PRIORITY: dict[str, dict[str, int]] = {
    "active_constraints": {"deprecated": 0, "inactive": 1, "active": 2},
    "memory_items":       {"deprecated": 0, "rejected": 1, "candidate": 2, "confirmed": 3},
    "memory_candidates":  {"rejected": 0, "proposed": 1, "promoted": 2},
}

# Column used for "oldest" ordering in each table
_OLDEST_ORDER: dict[str, str] = {
    "active_constraints": "created_at",
    "memory_items":       "created_at",
    "memory_candidates":  "created_at",
}

# Column that holds the status for each table
_STATUS_COL: dict[str, str] = {
    "active_constraints": "status",
    "memory_items":       "status",
    "memory_candidates":  "review_status",
}


# ── public API ─────────────────────────────────────────────────────

def check_budget(table: str) -> dict:
    """Return current row count vs limit for *table*.

    Returns ``{table, current, limit, over, headroom}``.
    """
    if table not in LIMITS:
        raise ValueError(f"unknown table: {table!r} (valid: {sorted(LIMITS)})")
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
    current: int = row["cnt"]
    limit = LIMITS[table]
    return {
        "table": table,
        "current": current,
        "limit": limit,
        "over": max(0, current - limit),
        "headroom": max(0, limit - current),
    }


def enforce_budget(table: str) -> dict:
    """Evict rows from *table* if it exceeds its budget limit.

    Eviction walks the oldest rows ordered by status priority (dead data
    first) and keeps at least ``_MIN_KEEP`` rows.

    Returns ``{evicted, remaining, strategy}``.
    """
    if table not in LIMITS:
        raise ValueError(f"unknown table: {table!r} (valid: {sorted(LIMITS)})")
    get_backend().init_schema()
    info = check_budget(table)
    if info["over"] == 0:
        return {"evicted": 0, "remaining": info["current"], "strategy": "none_under_budget"}

    limit = info["limit"]
    current = info["current"]
    target = limit  # evict down to exactly the limit
    to_remove = current - target
    order_col = _OLDEST_ORDER[table]

    conn = get_backend().connect()

    # Fetch all rows ordered by status priority (lowest first) then oldest first
    priority_cases = _STATUS_PRIORITY[table]
    status_col = _STATUS_COL[table]
    pk_col = "candidate_id" if table == "memory_candidates" else "id"

    # V3 P0-2: pinned memory items are protected from eviction.
    # For memory_items, we add `pinned DESC` first so non-pinned rows
    # are evicted before pinned ones. Other tables are unaffected.
    pinned_clause = ""
    if table == "memory_items":
        pinned_clause = "COALESCE(pinned, 0) DESC, "

    # Build a CASE expression for ORDER BY
    when_clauses = " ".join(
        f"WHEN {status_col} = ? THEN {pri}" for status, pri in sorted(priority_cases.items(), key=lambda x: x[1])
    ) + " ELSE 99"
    order_sql = f"{pinned_clause}(CASE {when_clauses} END) ASC, {order_col} ASC"
    params = [s for s, _ in sorted(priority_cases.items(), key=lambda x: x[1])]

    # For memory_items, only consider non-pinned rows for eviction
    where_extra = ""
    if table == "memory_items":
        where_extra = "WHERE COALESCE(pinned, 0) = 0"

    rows = conn.execute(
        f"SELECT {pk_col}, {status_col} FROM {table} {where_extra} ORDER BY {order_sql}",
        params,
    ).fetchall()

    # Always keep at least _MIN_KEEP rows — skip first _MIN_KEEP rows
    evictable = rows[_MIN_KEEP:]
    to_remove = min(to_remove, len(evictable))
    to_evict_ids = [r[pk_col] for r in evictable[:to_remove]]

    if not to_evict_ids:
        return {"evicted": 0, "remaining": current, "strategy": "min_keep_protection"}

    placeholders = ",".join("?" for _ in to_evict_ids)
    conn.execute(f"DELETE FROM {table} WHERE {pk_col} IN ({placeholders})", to_evict_ids)
    conn.commit()
    remaining = current - len(to_evict_ids)
    return {
        "evicted": len(to_evict_ids),
        "remaining": remaining,
        "strategy": "hard_delete_oldest",
    }


def budget_report() -> dict:
    """Full storage report: per-table counts + DB file size in bytes."""
    get_backend().init_schema()
    tables: dict[str, dict] = {}
    for table, limit in LIMITS.items():
        info = check_budget(table)
        tables[table] = info

    db_file = get_path_provider().memory_db_file()
    size_bytes = db_file.stat().st_size if db_file.exists() else 0

    return {
        "tables": tables,
        "db_file": str(db_file),
        "db_size_bytes": size_bytes,
    }
