"""Constraint derivation from Package 1 (Revision-First Gate) and Package 3
(Review Verdict Authority) events.

These hooks are called from tasks.py when revision_priority is set or
authoritative verdict is built. They auto-create active constraints so
workers retain critical rules after context loss.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def on_revision_priority_set(
    task_id: str,
    priority: str,
    *,
    reason: str = "",
    actor: str = "",
) -> None:
    """Package 1 hook: when revision_priority becomes non-empty, derive
    constraint '不能继续下一批/下一科目，必须先完成返修'.

    Called from set_revision_priority() and _apply_flow_review().
    """
    if not priority:
        return
    try:
        from eduflow.memory.constraints import add_constraint
    except ImportError:
        return

    try:
        content = (
            f"任务 {task_id} 当前 revision_priority={priority}："
            f"不能继续下一批/下一科目，必须先完成返修。"
        )
        source = f"task:{task_id}"
        add_constraint(
            scope=f"task:{task_id}",
            level="L2",
            constraint_type="gate_check",
            content=content,
            source_ref=source,
            enforcement="gate_required",
            created_by=actor or "system",
        )
        _log.debug("derived revision constraint for %s priority=%s", task_id, priority)
    except Exception as e:
        _log.warning("failed to derive revision constraint for %s: %s", task_id, e)


def on_authoritative_verdict_fail(
    task_id: str,
    verdict: dict,
) -> None:
    """Package 3 hook: when latest_authoritative_verdict outcome=fail,
    derive constraint 'manager不得closeout，必须等待worker repair + re-review'.

    Called from _apply_flow_review() after authoritative verdict is built.
    """
    if not isinstance(verdict, dict):
        return
    outcome = verdict.get("outcome", "")
    if outcome != "fail":
        return

    try:
        from eduflow.memory.constraints import add_constraint
    except ImportError:
        return

    try:
        reviewer = verdict.get("reviewer", "")
        review_reason = verdict.get("review_reason", "")
        content = (
            f"任务 {task_id} 最近 review verdict=FAIL (reviewer={reviewer})："
            f"manager 不得 closeout，必须等待 worker 完成修复并重新提交 review。"
        )
        if review_reason:
            content += f" 原因：{review_reason}"

        add_constraint(
            scope=f"task:{task_id}",
            level="L2",
            constraint_type="gate_check",
            content=content,
            source_ref=f"task:{task_id}",
            enforcement="gate_required",
            created_by=reviewer or "system",
        )
        _log.debug("derived verdict-fail constraint for %s", task_id)
    except Exception as e:
        _log.warning("failed to derive verdict-fail constraint for %s: %s", task_id, e)


def on_closeout_completed(task_id: str) -> None:
    """Supersede/close constraints that are no longer relevant after closeout.

    Called from manager_closeout_subject() after closeout_status is set.
    """
    try:
        from eduflow.memory.constraints import list_constraints, deactivate_constraint
    except ImportError:
        return

    try:
        constraints = list_constraints(scope=f"task:{task_id}", status="active")
        for c in constraints:
            deactivate_constraint(c["id"], reason=f"closeout completed for {task_id}")
        if constraints:
            _log.debug(
                "deactivated %d constraints for closed-out task %s",
                len(constraints), task_id,
            )
    except Exception as e:
        _log.warning("failed to deactivate constraints for closeout %s: %s", task_id, e)
