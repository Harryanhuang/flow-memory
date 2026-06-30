"""Daily summary / short-term memory layer (V3 P1-5).

Stores per-day agent session summaries with key decisions and open questions.
These are short-term memories that can be reflected into long-term memory
(memory_items) via the candidate pipeline.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flow_memory.storage import get_backend


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def upsert_summary(
    date: str,
    agent: str,
    summary: str,
    *,
    key_decisions: list[str] | None = None,
    open_questions: list[str] | None = None,
) -> str:
    """Insert or update a daily summary for the given agent/date."""
    get_backend().init_schema()
    if not date or not agent:
        raise ValueError("date and agent are required")
    if not summary.strip():
        raise ValueError("summary cannot be empty")

    decisions_json = json.dumps(key_decisions or [], ensure_ascii=False)
    questions_json = json.dumps(open_questions or [], ensure_ascii=False)

    now = _now_iso()
    conn = get_backend().connect()
    existing = conn.execute(
        "SELECT date FROM memory_daily_summary WHERE date = ? AND agent = ?",
        (date, agent),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE memory_daily_summary SET summary=?, key_decisions=?,
               open_questions=?, updated_at=? WHERE date=? AND agent=?""",
            (summary.strip(), decisions_json, questions_json, now, date, agent),
        )
    else:
        conn.execute(
            """INSERT INTO memory_daily_summary
               (date, agent, summary, key_decisions, open_questions, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (date, agent, summary.strip(), decisions_json, questions_json, now, now),
        )
    conn.commit()
    return f"{date}::{agent}"


def get_summary(date: str, agent: str) -> dict | None:
    """Fetch a single daily summary."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT * FROM memory_daily_summary WHERE date = ? AND agent = ?",
        (date, agent),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["key_decisions"] = json.loads(d.get("key_decisions") or "[]")
    d["open_questions"] = json.loads(d.get("open_questions") or "[]")
    return d


def list_summaries(
    *,
    agent: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """List daily summaries, optionally filtered."""
    get_backend().init_schema()
    conn = get_backend().connect()
    query = "SELECT * FROM memory_daily_summary WHERE 1=1"
    params: list = []
    if agent:
        query += " AND agent = ?"
        params.append(agent)
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " ORDER BY date DESC, agent LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["key_decisions"] = json.loads(d.get("key_decisions") or "[]")
        d["open_questions"] = json.loads(d.get("open_questions") or "[]")
        results.append(d)
    return results


def delete_summary(date: str, agent: str) -> bool:
    """Delete a daily summary."""
    get_backend().init_schema()
    conn = get_backend().connect()
    cur = conn.execute(
        "DELETE FROM memory_daily_summary WHERE date = ? AND agent = ?",
        (date, agent),
    )
    conn.commit()
    return cur.rowcount > 0


def archive_old_summaries(retention_days: int = 30) -> int:
    """Archive summaries older than retention_days. Returns count archived.

    For now this just deletes them. In a future iteration it could move
    them to an archive table or export to Obsidian before deletion.
    """
    get_backend().init_schema()
    cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Calculate cutoff date as YYYY-MM-DD
    from datetime import timedelta
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff = cutoff_dt.strftime("%Y-%m-%d")

    conn = get_backend().connect()
    cur = conn.execute(
        "DELETE FROM memory_daily_summary WHERE date < ?",
        (cutoff,),
    )
    conn.commit()
    return cur.rowcount