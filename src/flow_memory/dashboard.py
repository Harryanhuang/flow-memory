"""Memory visualization dashboard (V3 P2-4).

Produces a real-time dashboard view of memory health and activity,
inspired by Qoder's evolution dashboard.

Outputs trends (daily/weekly), high-frequency memories, candidate quality,
similar-pair counts, and pinned list. Can be printed to CLI or exported
to Obsidian.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flow_memory.storage import get_backend


def get_memory_trends(days: int = 7) -> list[dict]:
    """Return per-day memory_items and candidates write counts.

    Returns list of {date, items_added, candidates_added, items_deprecated}.
    """
    get_backend().init_schema()
    conn = get_backend().connect()

    # Compute date range
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days - 1)

    # Initialize per-day buckets
    buckets: dict[str, dict] = {}
    for i in range(days):
        d = (start_date + timedelta(days=i)).isoformat()
        buckets[d] = {
            "date": d,
            "items_added": 0,
            "items_deprecated": 0,
            "candidates_added": 0,
        }

    # Query items
    rows = conn.execute(
        """SELECT DATE(created_at) AS d, status, COUNT(*) AS cnt
           FROM memory_items
           WHERE DATE(created_at) >= ?
           GROUP BY DATE(created_at), status""",
        (start_date.isoformat(),),
    ).fetchall()
    for row in rows:
        d = row["d"]
        if d in buckets:
            if row["status"] == "confirmed":
                buckets[d]["items_added"] = row["cnt"]
            elif row["status"] == "deprecated":
                buckets[d]["items_deprecated"] = row["cnt"]

    # Query candidates
    rows = conn.execute(
        """SELECT DATE(created_at) AS d, COUNT(*) AS cnt
           FROM memory_candidates
           WHERE DATE(created_at) >= ?
           GROUP BY DATE(created_at)""",
        (start_date.isoformat(),),
    ).fetchall()
    for row in rows:
        d = row["d"]
        if d in buckets:
            buckets[d]["candidates_added"] = row["cnt"]

    return sorted(buckets.values(), key=lambda x: x["date"])


def get_top_injected_memories(days: int = 7, limit: int = 10) -> list[dict]:
    """Get memories most recently touched (proxy for injection frequency)."""
    get_backend().init_schema()
    conn = get_backend().connect()
    rows = conn.execute(
        """SELECT id, content, scope, kind, importance, updated_at
           FROM memory_items
           WHERE status='confirmed'
             AND updated_at >= ?
           ORDER BY updated_at DESC
           LIMIT ?""",
        ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(), limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_candidate_quality_distribution() -> dict:
    """Distribution of candidate counts by status."""
    get_backend().init_schema()
    conn = get_backend().connect()
    rows = conn.execute(
        """SELECT review_status, COUNT(*) AS cnt
           FROM memory_candidates
           GROUP BY review_status"""
    ).fetchall()
    total = sum(row["cnt"] for row in rows)
    return {
        "total": total,
        "by_status": {row["review_status"]: row["cnt"] for row in rows},
    }


def get_similar_pair_count(threshold: float = 0.85) -> int:
    """Count of similar-pair candidates (advisory only, best-effort)."""
    try:
        from flow_memory.consolidate import find_similar_pairs
        pairs = find_similar_pairs(threshold=threshold, limit_pairs=1000)
        return len(pairs)
    except Exception:
        return 0


def get_pinned_summary() -> dict:
    """Summary of pinned memories."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        """SELECT COUNT(*) AS total, COALESCE(MAX(importance), 0) AS max_importance
           FROM memory_items
           WHERE status='confirmed' AND COALESCE(pinned, 0) = 1"""
    ).fetchone()
    by_kind = conn.execute(
        """SELECT kind, COUNT(*) AS cnt
           FROM memory_items
           WHERE status='confirmed' AND COALESCE(pinned, 0) = 1
           GROUP BY kind"""
    ).fetchall()
    return {
        "total": row["total"] or 0,
        "max_importance": row["max_importance"] or 0,
        "by_kind": {r["kind"]: r["cnt"] for r in by_kind},
    }


def render_dashboard(days: int = 7) -> str:
    """Render the full dashboard as a markdown string."""
    trends = get_memory_trends(days)
    top = get_top_injected_memories(days=days, limit=5)
    quality = get_candidate_quality_distribution()
    pinned = get_pinned_summary()
    similar = get_similar_pair_count()

    lines = []
    lines.append(f"# 📊 EduFlow Memory Dashboard")
    lines.append(f"_Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}_")
    lines.append("")

    # Trends
    lines.append(f"## 📈 Trends (last {days} days)")
    lines.append("")
    lines.append("| Date | Items Added | Items Deprecated | Candidates Added |")
    lines.append("|------|-------------|------------------|------------------|")
    for t in trends:
        lines.append(
            f"| {t['date']} | {t['items_added']} | {t['items_deprecated']} | {t['candidates_added']} |"
        )
    lines.append("")

    # Top injected
    lines.append("## 🔥 Recently Touched (proxy for high-injection)")
    lines.append("")
    if top:
        for m in top:
            content_preview = m["content"][:60].replace("\n", " ")
            lines.append(f"- **[{m['id']}]** [{m['kind']}] scope={m['scope']} (imp={m['importance']})")
            lines.append(f"  {content_preview}")
    else:
        lines.append("_No recently touched memories._")
    lines.append("")

    # Candidate quality
    lines.append("## 📋 Candidate Quality Distribution")
    lines.append("")
    lines.append(f"- **Total candidates**: {quality['total']}")
    for status, cnt in quality["by_status"].items():
        lines.append(f"  - {status}: {cnt}")
    lines.append("")

    # Similar pairs
    lines.append("## 🔁 Consolidation")
    lines.append("")
    lines.append(f"- **Similar pairs detected (threshold=0.85)**: {similar}")
    lines.append(f"  - Run `eduflow memory consolidate --report` for details")
    lines.append("")

    # Pinned
    lines.append("## 📌 Pinned Memories (curated core)")
    lines.append("")
    lines.append(f"- **Total pinned**: {pinned['total']}")
    lines.append(f"- **Max importance**: {pinned['max_importance']}")
    for kind, cnt in pinned.get("by_kind", {}).items():
        lines.append(f"  - {kind}: {cnt}")
    lines.append("")
    lines.append(f"  - Run `eduflow memory pin list` for details")
    lines.append("")

    return "\n".join(lines)