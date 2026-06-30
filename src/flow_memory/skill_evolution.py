"""Skill evolution skeleton (V3 P3-3).

Detects high-frequency confirmed rules and proposes AGENTS.md update
suggestions. Maintains a cooldown state machine so rejected
suggestions don't get re-proposed for a configurable period.

Inspired by Qoder's "技能进化" (skill evolution) flow:
  1. Cluster frequent confirmed rules
  2. Generate diff-format suggestions for AGENTS.md updates
  3. User/manager accepts / ignores / rejects
  4. Rejected suggestions enter cooldown, won't be re-proposed until cooldown expires
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from flow_memory.storage import get_backend


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Suggestion generation ──────────────────────────────────────────

def aggregate_frequent_rules(
    *,
    kinds: list[str] | None = None,
    scope: str | None = None,
    min_importance: int = 7,
    min_age_days: int = 7,
    limit: int = 20,
) -> list[dict]:
    """Aggregate high-frequency confirmed rules.

    Returns list of {id, content, scope, kind, importance, evidence_count}
    sorted by importance + recency.
    """
    if kinds is None:
        kinds = ["workflow_rule", "role_rule", "runtime_rule"]

    conn = get_backend().connect()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=min_age_days)).isoformat()

    query = """
        SELECT id, content, scope, kind, importance, created_at, updated_at,
               evidence_refs, summary
        FROM memory_items
        WHERE status='confirmed'
          AND importance >= ?
          AND created_at <= ?
          AND kind IN ({})
    """.format(",".join("?" * len(kinds)))
    params: list = [min_importance, cutoff, *kinds]

    if scope:
        query += " AND scope = ?"
        params.append(scope)

    query += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    results = []
    for r in rows:
        try:
            evidence = json.loads(r["evidence_refs"] or "[]")
        except (json.JSONDecodeError, TypeError):
            evidence = []
        results.append({
            "id": r["id"],
            "content": r["content"],
            "scope": r["scope"],
            "kind": r["kind"],
            "importance": r["importance"],
            "evidence_count": len(evidence),
            "summary": r["summary"] or "",
        })
    return results


def generate_suggestions(
    *,
    kinds: list[str] | None = None,
    scope: str | None = None,
    min_importance: int = 7,
    min_age_days: int = 7,
    cooldown_hours: int = 168,  # 7 days default
) -> list[dict]:
    """Generate AGENTS.md update suggestions from frequent rules.

    Returns list of {rule_id, content, scope, kind, importance, rationale,
    diff_text, cooldown_until (None if not in cooldown)}.
    """
    rules = aggregate_frequent_rules(
        kinds=kinds, scope=scope, min_importance=min_importance,
        min_age_days=min_age_days,
    )

    suggestions = []
    for rule in rules:
        cooldown_until = _get_cooldown(rule["id"])
        if cooldown_until is not None:
            # Skip rules in cooldown
            continue

        rationale = (
            f"[{rule['kind']}] (imp={rule['importance']}, "
            f"evidence={rule['evidence_count']}) {rule['content'][:80]}"
        )
        diff_text = _build_diff_text(rule)

        suggestions.append({
            "rule_id": rule["id"],
            "content": rule["content"],
            "scope": rule["scope"],
            "kind": rule["kind"],
            "importance": rule["importance"],
            "rationale": rationale,
            "diff_text": diff_text,
            "cooldown_until": None,
        })
    return suggestions


def _build_diff_text(rule: dict) -> str:
    """Build a unified-diff-like text for the suggested AGENTS.md addition."""
    return (
        f"+ [{rule['kind']}] {rule['content']} "
        f"# from {rule['id']} (imp={rule['importance']})\n"
    )


# ── Cooldown state machine ─────────────────────────────────────────

def _cooldown_table() -> str:
    return "memory_skill_cooldowns"


def _init_cooldown_table() -> None:
    """Create the cooldown table if not exists."""
    conn = get_backend().connect()
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_cooldown_table()} (
            rule_id TEXT PRIMARY KEY,
            rejected_at TEXT NOT NULL,
            cooldown_until TEXT NOT NULL,
            reason TEXT DEFAULT '',
            reject_count INTEGER DEFAULT 1
        )
    """)
    conn.commit()


def _get_cooldown(rule_id: str) -> str | None:
    """Return cooldown_until ISO timestamp if in cooldown, else None."""
    _init_cooldown_table()
    conn = get_backend().connect()
    row = conn.execute(
        f"SELECT cooldown_until FROM {_cooldown_table()} WHERE rule_id = ?",
        (rule_id,),
    ).fetchone()
    if row is None:
        return None
    until = row["cooldown_until"]
    if datetime.fromisoformat(until) > datetime.now(timezone.utc):
        return until
    # Cooldown expired, clean up
    conn.execute(f"DELETE FROM {_cooldown_table()} WHERE rule_id = ?", (rule_id,))
    conn.commit()
    return None


def reject_suggestion(rule_id: str, *, reason: str = "", cooldown_hours: int = 168) -> None:
    """Mark a suggestion as rejected; enters cooldown.

    If the rule was already rejected, increments reject_count and
    extends cooldown (exponential backoff: 1x, 2x, 4x, ... max 30 days).
    """
    _init_cooldown_table()
    conn = get_backend().connect()
    existing = conn.execute(
        f"SELECT reject_count FROM {_cooldown_table()} WHERE rule_id = ?",
        (rule_id,),
    ).fetchone()

    now = datetime.now(timezone.utc)
    if existing:
        reject_count = existing["reject_count"] + 1
        # Exponential backoff capped at 30 days
        multiplier = min(2 ** (reject_count - 1), 30 * 24 / cooldown_hours)
        cooldown_h = cooldown_hours * multiplier
    else:
        reject_count = 1
        cooldown_h = cooldown_hours

    until = (now + timedelta(hours=cooldown_h)).isoformat()

    if existing:
        conn.execute(
            f"""UPDATE {_cooldown_table()}
                SET rejected_at=?, cooldown_until=?, reason=?, reject_count=?
                WHERE rule_id=?""",
            (_now_iso(), until, reason, reject_count, rule_id),
        )
    else:
        conn.execute(
            f"""INSERT INTO {_cooldown_table()}
                (rule_id, rejected_at, cooldown_until, reason, reject_count)
                VALUES (?, ?, ?, ?, ?)""",
            (rule_id, _now_iso(), until, reason, reject_count),
        )
    conn.commit()


def accept_suggestion(rule_id: str) -> bool:
    """Mark a suggestion as accepted; clears any cooldown.

    Returns True if a cooldown was cleared, False otherwise.
    """
    _init_cooldown_table()
    conn = get_backend().connect()
    cur = conn.execute(
        f"DELETE FROM {_cooldown_table()} WHERE rule_id = ?", (rule_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def list_active_cooldowns(limit: int = 50) -> list[dict]:
    """List all rules currently in cooldown (advisory only)."""
    _init_cooldown_table()
    conn = get_backend().connect()
    rows = conn.execute(
        f"""SELECT * FROM {_cooldown_table()}
            WHERE cooldown_until > ?
            ORDER BY cooldown_until DESC LIMIT ?""",
        (datetime.now(timezone.utc).isoformat(), limit),
    ).fetchall()
    return [dict(r) for r in rows]


def clear_all_cooldowns() -> int:
    """Clear all cooldowns. Returns number deleted."""
    _init_cooldown_table()
    conn = get_backend().connect()
    cur = conn.execute(f"DELETE FROM {_cooldown_table()}")
    conn.commit()
    return cur.rowcount


# ── CLI helpers ────────────────────────────────────────────────────

def render_suggestion_report(
    *,
    kinds: list[str] | None = None,
    scope: str | None = None,
    min_importance: int = 7,
    cooldown_hours: int = 168,
) -> str:
    """Render skill evolution suggestions as a markdown report."""
    suggestions = generate_suggestions(
        kinds=kinds, scope=scope,
        min_importance=min_importance, cooldown_hours=cooldown_hours,
    )
    cooldowns = list_active_cooldowns(limit=20)

    lines: list[str] = []
    lines.append("# 🧬 Skill Evolution Suggestions")
    lines.append("")
    lines.append(f"_Generated: {_now_iso()}_")
    lines.append("")
    lines.append(f"## Pending Suggestions ({len(suggestions)})")
    lines.append("")

    if not suggestions:
        lines.append("_No new suggestions. All frequent rules either in cooldown or already in AGENTS.md._")
        lines.append("")
    else:
        for i, s in enumerate(suggestions, 1):
            lines.append(f"### {i}. [{s['kind']}] {s['content'][:80]}")
            lines.append(f"- **rule_id**: `{s['rule_id']}`")
            lines.append(f"- **scope**: `{s['scope']}`")
            lines.append(f"- **importance**: {s['importance']}")
            lines.append(f"- **rationale**: {s['rationale']}")
            lines.append("")
            lines.append("```diff")
            lines.append(s["diff_text"].rstrip())
            lines.append("```")
            lines.append("")
            lines.append(f"Accept: `eduflow memory skill-evolve accept {s['rule_id']}`")
            lines.append(f"Reject: `eduflow memory skill-evolve reject {s['rule_id']} --reason \"...\"`")
            lines.append("")

    lines.append(f"## Active Cooldowns ({len(cooldowns)})")
    lines.append("")
    if not cooldowns:
        lines.append("_None._")
        lines.append("")
    else:
        for c in cooldowns:
            lines.append(f"- `{c['rule_id']}` — until {c['cooldown_until'][:19]} (rejected {c['reject_count']}x)")
        lines.append("")

    return "\n".join(lines)