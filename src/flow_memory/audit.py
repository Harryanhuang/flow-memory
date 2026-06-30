"""Audit statistics and reports for EduFlow Memory.

Provides read-only aggregation queries for monitoring DB health:
  - full_audit: row counts by status across all tables
  - scope_coverage_report: confirmed memories grouped by scope
  - retention_report: lifecycle stats within a time window
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flow_memory.storage import get_backend


def full_audit() -> dict:
    """Return row counts grouped by status for every meaningful table.

    Returns a dict keyed by table name, each value a dict of status→count.
    Tables without a status column (task_capsules, memory_scope_aliases)
    return their total row count under a ``_total`` key.
    """
    get_backend().init_schema()
    conn = get_backend().connect()
    result: dict[str, dict[str, int]] = {}

    # Tables with a status column
    for table, status_col in [
        ("active_constraints", "status"),
        ("memory_items", "status"),
        ("memory_candidates", "review_status"),
    ]:
        rows = conn.execute(
            f"SELECT {status_col} AS status, COUNT(*) AS cnt "
            f"FROM {table} GROUP BY {status_col}"
        ).fetchall()
        result[table] = {r["status"]: r["cnt"] for r in rows}

    # Tables without a status column
    for table in ("task_capsules", "memory_scope_aliases"):
        row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
        result[table] = {"_total": row["cnt"]}

    return result


def scope_coverage_report() -> list[dict]:
    """Confirmed memory_items grouped by scope, with kind breakdown.

    Returns a list sorted by scope name:
      [{scope, total, kinds: {kind: count}}, ...]
    """
    get_backend().init_schema()
    conn = get_backend().connect()
    rows = conn.execute(
        "SELECT scope, kind, COUNT(*) AS cnt "
        "FROM memory_items WHERE status = 'confirmed' "
        "GROUP BY scope, kind "
        "ORDER BY scope, kind"
    ).fetchall()

    by_scope: dict[str, dict] = {}
    for r in rows:
        scope = r["scope"]
        if scope not in by_scope:
            by_scope[scope] = {"scope": scope, "total": 0, "kinds": {}}
        by_scope[scope]["kinds"][r["kind"]] = r["cnt"]
        by_scope[scope]["total"] += r["cnt"]

    return sorted(by_scope.values(), key=lambda x: x["scope"])


def retention_report(days: int = 90) -> dict:
    """Lifecycle stats for the past *days* days.

    Counts rows created, confirmed, deprecated/promoted/rejected within
    the window. Separate queries for each table to keep logic simple.

    Returns a dict with keys: period_days, window_start, items, candidates,
    constraints.
    """
    get_backend().init_schema()
    conn = get_backend().connect()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()

    # Memory items: created/confirmed/deprecated in window
    item_rows = conn.execute(
        "SELECT "
        "  SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS created, "
        "  SUM(CASE WHEN status = 'confirmed' AND updated_at >= ? THEN 1 ELSE 0 END) AS confirmed, "
        "  SUM(CASE WHEN status = 'deprecated' AND updated_at >= ? THEN 1 ELSE 0 END) AS deprecated "
        "FROM memory_items",
        (cutoff, cutoff, cutoff),
    ).fetchone()

    # Candidates: proposed/promoted/rejected in window
    cand_rows = conn.execute(
        "SELECT "
        "  SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS proposed, "
        "  SUM(CASE WHEN review_status = 'promoted' AND reviewed_at >= ? THEN 1 ELSE 0 END) AS promoted, "
        "  SUM(CASE WHEN review_status = 'rejected' AND reviewed_at >= ? THEN 1 ELSE 0 END) AS rejected "
        "FROM memory_candidates",
        (cutoff, cutoff, cutoff),
    ).fetchone()

    # Constraints: created/inactivated in window
    con_rows = conn.execute(
        "SELECT "
        "  SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) AS created, "
        "  SUM(CASE WHEN status = 'inactive' AND updated_at >= ? THEN 1 ELSE 0 END) AS inactivated "
        "FROM active_constraints",
        (cutoff, cutoff),
    ).fetchone()

    return {
        "period_days": days,
        "window_start": cutoff,
        "items": {
            "created": item_rows["created"] or 0,
            "confirmed": item_rows["confirmed"] or 0,
            "deprecated": item_rows["deprecated"] or 0,
        },
        "candidates": {
            "proposed": cand_rows["proposed"] or 0,
            "promoted": cand_rows["promoted"] or 0,
            "rejected": cand_rows["rejected"] or 0,
        },
        "constraints": {
            "created": con_rows["created"] or 0,
            "inactivated": con_rows["inactivated"] or 0,
        },
    }
