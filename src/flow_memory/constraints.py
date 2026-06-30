"""Active Constraints CRUD and scope-based query.

Constraints are stored in SQLite and queried by scope + level hierarchy:
  L0 (team) → L1 (lane/workflow) → L2 (task) → L3 (ephemeral)

Query order: team → lane → workflow → task (deduplicated by content).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flow_memory.storage import get_backend

_VALID_LEVELS = frozenset({"L0", "L1", "L2", "L3"})
_VALID_TYPES = frozenset({
    "must_follow", "must_not", "gate_check",
    "escalation_rule", "evidence_rule",
})
_VALID_STATUSES = frozenset({"active", "inactive", "deprecated"})
_VALID_ENFORCEMENTS = frozenset({"prompt_only", "packet_required", "gate_required"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_id(now: str) -> str:
    date_part = now[:10].replace("-", "")
    prefix = f"AC-{date_part}-"
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(id, ?) AS INTEGER)) FROM active_constraints WHERE id LIKE ?",
        (len(prefix) + 1, f"{prefix}%"),
    ).fetchone()
    seq = (row[0] or 0) + 1
    return f"AC-{date_part}-{seq:03d}"


def add_constraint(
    scope: str,
    level: str,
    constraint_type: str,
    content: str,
    *,
    source_ref: str = "",
    evidence_refs: list[str] | None = None,
    enforcement: str = "prompt_only",
    injection_point: str = "send,reidentify,compact",
    valid_until: str = "",
    created_by: str = "",
) -> str:
    """Add a new active constraint. Returns the constraint ID."""
    if level not in _VALID_LEVELS:
        raise ValueError(f"invalid level: {level} (valid: {sorted(_VALID_LEVELS)})")
    if constraint_type not in _VALID_TYPES:
        raise ValueError(f"invalid type: {constraint_type} (valid: {sorted(_VALID_TYPES)})")
    if enforcement not in _VALID_ENFORCEMENTS:
        raise ValueError(f"invalid enforcement: {enforcement} (valid: {sorted(_VALID_ENFORCEMENTS)})")
    if not content.strip():
        raise ValueError("content cannot be empty")

    get_backend().init_schema()
    now = _now_iso()
    cid = _next_id(now)
    conn = get_backend().connect()
    conn.execute(
        """INSERT INTO active_constraints
           (id, scope, constraint_level, constraint_type, content,
            source_ref, evidence_refs, status, enforcement, injection_point,
            valid_from, valid_until, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)""",
        (
            cid, scope, level, constraint_type, content.strip(),
            source_ref, json.dumps(evidence_refs or []),
            enforcement, injection_point,
            now, valid_until, created_by, now, now,
        ),
    )
    conn.commit()
    return cid


def get_constraint(constraint_id: str) -> dict | None:
    """Fetch a single constraint by ID."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT * FROM active_constraints WHERE id = ?", (constraint_id,)
    ).fetchone()
    return dict(row) if row else None


def list_constraints(
    *,
    scope: str | None = None,
    status: str = "active",
    level: str | None = None,
) -> list[dict]:
    """List constraints, optionally filtered by scope, status, level."""
    get_backend().init_schema()
    conn = get_backend().connect()
    query = "SELECT * FROM active_constraints WHERE 1=1"
    params: list = []
    if scope:
        query += " AND scope = ?"
        params.append(scope)
    if status:
        query += " AND status = ?"
        params.append(status)
    if level:
        query += " AND constraint_level = ?"
        params.append(level)
    query += " ORDER BY constraint_level, created_at"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def deactivate_constraint(constraint_id: str, *, reason: str = "") -> bool:
    """Mark a constraint as inactive. Returns True if found and changed."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT status FROM active_constraints WHERE id = ?",
        (constraint_id,),
    ).fetchone()
    if row is None:
        return False
    if row["status"] == "inactive":
        return False
    now = _now_iso()
    conn.execute(
        "UPDATE active_constraints SET status = 'inactive', updated_at = ? WHERE id = ?",
        (now, constraint_id),
    )
    conn.commit()
    return True


def supersede_constraint(old_id: str, new_id: str) -> bool:
    """Mark old constraint as superseded by new_id. Returns True if changed."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT status FROM active_constraints WHERE id = ?",
        (old_id,),
    ).fetchone()
    if row is None:
        return False
    now = _now_iso()
    conn.execute(
        "UPDATE active_constraints SET status = 'inactive', updated_at = ? WHERE id = ?",
        (now, old_id),
    )
    conn.commit()
    return True


def query_for_agent(
    agent: str,
    task_id: str | None = None,
    *,
    injection_point: str | None = None,
) -> list[dict]:
    """Query active constraints for an agent, aggregating scope hierarchy.

    Returns constraints in priority order: L0 team → L1 lane/workflow → L2 task.
    Deduplicates by content (first occurrence wins).

    When ``injection_point`` is set (e.g. "send", "reidentify", "compact"),
    only constraints whose ``injection_point`` column contains that token
    are returned. The filter is applied at the SQL layer so callers don't
    pay for constraints that target a different injection site.
    """
    get_backend().init_schema()
    conn = get_backend().connect()

    # Collect active constraints. The injection_point filter is pushed
    # into the WHERE clause — ``injection_point`` is stored as a
    # comma-separated token list ("send,reidentify,compact"), so we
    # match with LIKE '%token%'. Safe because tokens are short, no
    # commas, no wildcards in practice.
    if injection_point:
        rows = conn.execute(
            "SELECT * FROM active_constraints WHERE status = 'active' "
            "AND (injection_point = '' OR injection_point LIKE ?)",
            (f"%{injection_point}%",),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM active_constraints WHERE status = 'active'"
        ).fetchall()

    # Build scope match set for this agent+task
    result: list[dict] = []
    seen_content: set[str] = set()

    # Priority order: L0 → L1 → L2 → L3
    level_priority = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}

    # Match scopes: team, lane:<agent>, workflow:<agent>, task:<task_id>
    matched_scopes = {"team"}
    # We don't know lane mapping yet — match any lane scope
    # In practice, lane resolution would come from config; for now
    # we include all L0 team constraints + any L1/L2 that match
    for row in rows:
        scope = row["scope"]
        level = row["constraint_level"]
        content = row["content"]

        scope_match = False
        if scope == "team":
            scope_match = True
        elif scope.startswith("task:") and task_id:
            scope_match = scope == f"task:{task_id}"
        # lane/workflow scopes: include if agent is the owner (simple heuristic)
        elif scope.startswith("lane:") or scope.startswith("workflow:"):
            scope_match = True  # include all lane/workflow for now

        if scope_match and content not in seen_content:
            seen_content.add(content)
            result.append(dict(row))

    # Sort by level priority, then by created_at
    result.sort(key=lambda r: (level_priority.get(r["constraint_level"], 9), r["created_at"]))
    return result
