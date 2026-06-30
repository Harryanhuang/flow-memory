"""Task Capsules CRUD and refresh from tasks.json.

A Task Capsule is a compact snapshot of a flow task's essential context,
stored in SQLite so it can be injected into Memory Packets after context loss.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flow_memory.storage import get_backend


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_capsule(
    task_id: str,
    *,
    workflow_id: str = "",
    owner: str = "",
    gate: str = "",
    goal: str = "",
    acceptance: str = "",
    current_status: str = "",
    decisions: list[str] | None = None,
    blockers: list[str] | None = None,
    next_action: str = "",
    last_evidence_ref: str = "",
) -> None:
    """Insert or update a task capsule."""
    get_backend().init_schema()
    now = _now_iso()
    conn = get_backend().connect()
    conn.execute(
        """INSERT INTO task_capsules
           (task_id, workflow_id, owner, gate, goal, acceptance,
            current_status, decisions, blockers, next_action,
            last_evidence_ref, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(task_id) DO UPDATE SET
             workflow_id = excluded.workflow_id,
             owner = excluded.owner,
             gate = excluded.gate,
             goal = excluded.goal,
             acceptance = excluded.acceptance,
             current_status = excluded.current_status,
             decisions = excluded.decisions,
             blockers = excluded.blockers,
             next_action = excluded.next_action,
             last_evidence_ref = excluded.last_evidence_ref,
             updated_at = excluded.updated_at""",
        (
            task_id, workflow_id, owner, gate, goal, acceptance,
            current_status,
            json.dumps(decisions or []),
            json.dumps(blockers or []),
            next_action, last_evidence_ref, now,
        ),
    )
    conn.commit()


def get_capsule(task_id: str) -> dict | None:
    """Fetch a single task capsule by task_id."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT * FROM task_capsules WHERE task_id = ?", (task_id,)
    ).fetchone()
    return dict(row) if row else None


def refresh_from_task_store(task_id: str) -> dict | None:
    """Read a task from tasks.json and rebuild its capsule.

    Returns the capsule dict, or None if task not found / not a flow task.
    """
    try:
        from eduflow.store import tasks as _tasks
    except ImportError:
        return None

    # Read task directly via the store's public API
    try:
        task = _tasks.get(task_id)
    except Exception:
        return None
    if task is None:
        return None
    if task.get("schema_version") != 2:
        return None

    # Build capsule fields from task state
    verdict = task.get("verdict") or ""
    closeout = task.get("closeout_status") or ""
    revision = task.get("revision_priority") or ""

    # Determine gate
    gate = ""
    if closeout:
        gate = f"closeout:{closeout}"
    elif verdict == "pending":
        gate = "review_pending"
    elif verdict in ("approved", "rejected"):
        gate = f"verdict:{verdict}"

    # Build blockers from task state
    blockers: list[str] = []
    if revision:
        blockers.append(f"revision_priority={revision}")
    if closeout and closeout not in ("", "closeout_completed"):
        blockers.append(f"closeout_status={closeout}")

    # Determine next action
    status = task.get("status") or ""
    next_action = ""
    if status == "submitted_for_review":
        next_action = "awaiting_review"
    elif status == "in_progress":
        next_action = "continue_work"
    elif status == "delivered":
        next_action = "pending_closeout"
    elif revision:
        next_action = "address_revision"

    # Build goal from title + scope
    title = task.get("title") or ""
    scope_topic = task.get("scope_topic") or ""
    goal = title
    if scope_topic:
        goal = f"{title} ({scope_topic})"

    # Build acceptance from required_fix + blocking_files
    required_fix = task.get("required_fix") or []
    acceptance_parts: list[str] = []
    if required_fix:
        acceptance_parts.extend(required_fix)
    acceptance = "; ".join(acceptance_parts)

    # Evidence ref
    evidence = task.get("evidence_packet") or {}
    last_evidence = ""
    if evidence:
        last_evidence = f"evidence_snapshot:{task.get('evidence_snapshot_hash', '')}"

    upsert_capsule(
        task_id,
        workflow_id=task.get("workflow_id") or "",
        owner=task.get("owner") or task.get("assignee") or "",
        gate=gate,
        goal=goal,
        acceptance=acceptance,
        current_status=status,
        decisions=[],
        blockers=blockers,
        next_action=next_action,
        last_evidence_ref=last_evidence,
    )
    return get_capsule(task_id)
