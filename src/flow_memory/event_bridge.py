"""Event bridge — translate runtime events into memory candidates.

This module sits between runtime code paths (review verdict, closeout
check, manager corrections, task lifecycle) and the
:mod:`eduflow.memory.event_hooks` module that actually builds the
candidate rows. The bridge's job is *translation*: runtime events use
one shape (a review result dict, a closeout count triple, a lifecycle
event name); hooks expect another (a normalized event_ctx dict with
specific keys).

Every bridge function:
  1. Validates the minimum required fields are present.
  2. Translates runtime names into hook names (e.g. "REJECTED" → hook fires).
  3. Calls the hook inside try/except — bridge failures never crash
     the runtime path.
  4. Returns the candidate_id on success, None if the event was
     filtered out or translation failed.

Idempotency is inherited from :func:`add_candidate`: firing the same
bridge twice with the same source_ref returns the same candidate_id
without creating a duplicate row.
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


# ── Helper ────────────────────────────────────────────────────────

def _call_hook(hook_fn, event_ctx: dict, *, label: str) -> str | None:
    """Invoke a hook, swallow errors, return candidate_id or None.

    Why wrap every call: runtime paths that invoke bridges (review,
    closeout, lifecycle) are on the critical path for worker task
    completion. A memory-system bug must not fail those operations.
    """
    try:
        return hook_fn(event_ctx)
    except Exception:
        _log.warning(
            "event_bridge %s: hook failed for ctx=%s",
            label, event_ctx, exc_info=True,
        )
        return None


# ── Bridge: review event ─────────────────────────────────────────

_FAIL_VERDICTS = frozenset({"FAIL", "REJECTED", "fail", "rejected"})


def bridge_review_event(review_result: dict[str, Any]) -> str | None:
    """Bridge a review result into :func:`on_review_rejected`.

    Expected review_result keys:
      task_id        — required
      worker         — optional; becomes worker_name in hook ctx
      verdict        — required; only "FAIL" / "REJECTED" fire the hook
      reason         — optional; becomes reject_reason
      review_content — optional

    Returns candidate_id on fire, None if verdict was non-fail or
    required fields were missing.
    """
    if not isinstance(review_result, dict):
        return None
    verdict = str(review_result.get("verdict") or "").strip()
    if verdict not in _FAIL_VERDICTS:
        # Pass / manager_action / unknown — not a candidate-worthy event.
        return None
    task_id = review_result.get("task_id", "")
    if not task_id:
        return None
    try:
        from eduflow.memory.event_hooks import on_review_rejected
    except ImportError:
        _log.warning("event_bridge: event_hooks unavailable")
        return None

    event_ctx = {
        "task_id": task_id,
        "worker_name": review_result.get("worker") or "",
        "reject_reason": review_result.get("reason") or "",
        "review_content": review_result.get("review_content") or "",
        # Carry through optional fields the hook can use for scope
        # inference (workflow_id, etc.).
        "workflow_id": review_result.get("workflow_id") or "",
    }
    return _call_hook(on_review_rejected, event_ctx, label="review_event")


# ── Bridge: closeout check ───────────────────────────────────────

def bridge_closeout_check(
    task_id: str,
    items_count: int,
    qql_count: int,
    manifest_count: int,
    *,
    agent: str = "",
    workflow_id: str = "",
) -> dict[str, Any]:
    """Bridge closeout consistency check.

    Returns:
      consistent:          bool — True if the three counts agree.
      candidate_id:        str | None — candidate created if inconsistent.
      blocking_constraints: list[dict] — from build_gate_check.

    Anomaly fires whenever any of the three counts differ. Even when
    consistent, we still run the gate check so any ``gate_required``
    constraint is surfaced to the caller.
    """
    result: dict[str, Any] = {
        "consistent": True,
        "candidate_id": None,
        "blocking_constraints": [],
    }

    # 1. Consistency check
    counts = {items_count, qql_count, manifest_count}
    consistent = len(counts) == 1
    result["consistent"] = consistent

    if not consistent:
        try:
            from eduflow.memory.event_hooks import on_closeout_anomaly
        except ImportError:
            _log.warning("event_bridge: event_hooks unavailable")
        else:
            event_ctx = {
                "task_id": task_id,
                "anomaly_type": "closeout_count_mismatch",
                "expected_value": str(items_count),
                "actual_value": f"items={items_count} qql={qql_count} manifest={manifest_count}",
                "workflow_id": workflow_id,
            }
            result["candidate_id"] = _call_hook(
                on_closeout_anomaly, event_ctx, label="closeout_check",
            )

    # 2. Gate check (always — even consistent closeouts can be blocked)
    if agent:
        try:
            from eduflow.memory.inject import build_gate_check
            gate = build_gate_check(agent, task_id, gate_name="closeout")
            result["blocking_constraints"] = gate.get("blocking_constraints", [])
        except Exception:
            _log.warning(
                "event_bridge closeout gate_check failed", exc_info=True,
            )

    return result


# ── Bridge: manager correction ───────────────────────────────────

def bridge_manager_correction(
    agent: str,
    content: str,
    *,
    severity: str = "medium",
    context: str = "",
) -> str | None:
    """Bridge a manager's explicit correction into a candidate.

    Always fires (manager corrections are deliberate knowledge
    transfers). Returns candidate_id on success, None on failure.
    """
    if not agent or not content:
        return None
    try:
        from eduflow.memory.event_hooks import on_manager_correction
    except ImportError:
        _log.warning("event_bridge: event_hooks unavailable")
        return None

    event_ctx = {
        "target_agent": agent,
        "correction_content": content,
        "severity": severity,
        "context": context,
    }
    return _call_hook(
        on_manager_correction, event_ctx, label="manager_correction",
    )


# ── Bridge: task lifecycle ───────────────────────────────────────

def _count_prior_failures(workflow_id: str) -> int:
    """Count prior failure-related candidates for this workflow.

    We count candidates of ANY source_type scoped to the workflow,
    because a "failure" can be represented by:
      - a review_reject candidate (individual failure event),
      - an existing task_failure_pattern candidate (already-detected
        pattern),
      - any other source the hook caller may have produced.
    Treating them all as evidence of "this workflow has had trouble"
    lets the pattern detector fire as soon as there's a second
    signal — regardless of which hook produced the first.

    Returns 0 on any error — under-counting means we wait one more
    failure, not that we miss the pattern entirely.
    """
    try:
        from eduflow.memory.candidate_gen import list_candidates
        existing = list_candidates(
            scope=f"workflow:{workflow_id}",
            status="proposed",
            limit=100,
        )
        return len(existing)
    except Exception:
        return 0


def bridge_task_lifecycle(
    task_id: str,
    event: str,
    context: dict[str, Any] | None = None,
) -> str | None:
    """Bridge task lifecycle events.

    Recognized events:
      "fail"    — records the failure and, once the workflow has
                  accumulated ≥2 failures, fires task_failure_pattern.
      "retry"   — counted via the failure tracking in "fail".
      "success" — no-op for memory (success patterns are for
                  reinforcement, a future feature).

    How pattern detection works:
      Every "fail" event creates a witness candidate with
      ``source_type="task_failure"`` (idempotent by task_id, so
      retrying the same task doesn't double-count). After the
      witness is recorded we recount the workflow's failures;
      if the total is ≥2, we also fire on_task_failure_pattern
      which produces the "pattern detected" candidate.

    The function returns the pattern candidate_id when the
    threshold is crossed, and None otherwise — matching the test
    contract "1 次不生成, 2 次生成".

    context may contain:
      workflow_id      — required to group failures into a pattern
      failure_reason   — optional, becomes failure_reasons[0]
      failure_reasons  — optional list (overrides failure_reason)
      task_ids         — optional list (defaults to [task_id])

    Returns candidate_id on fire, None if event was filtered or
    threshold not reached.
    """
    ctx = context or {}
    event_lower = str(event or "").strip().lower()
    if event_lower != "fail":
        # Only "fail" produces candidates today. retry/success are
        # reserved for future pattern detectors.
        return None

    workflow_id = ctx.get("workflow_id", "")
    if not workflow_id or not task_id:
        return None

    # 1. Record this individual failure as a witness candidate.
    # Idempotent by (source_type="task_failure", source_ref="task:X"),
    # so a retry of the same task doesn't double-count.
    reasons = ctx.get("failure_reasons") or []
    if not reasons and ctx.get("failure_reason"):
        reasons = [ctx["failure_reason"]]
    reason_text = reasons[0] if reasons else "no reason given"
    try:
        from eduflow.memory.candidate_gen import add_candidate
        add_candidate(
            scope=f"workflow:{workflow_id}",
            kind="mistake",
            content=f"任务 {task_id} 在 workflow {workflow_id} 中失败：{reason_text}",
            source_type="task_failure",
            source_ref=f"task:{task_id}",
            layer="episode",
            reason=f"task failure in {workflow_id}",
            evidence_refs=[f"task:{t}" for t in (ctx.get("task_ids") or [task_id])[:5]],
            risk_flags=["failure"],
        )
    except Exception:
        _log.warning(
            "event_bridge task_lifecycle: failed to record witness for %s",
            task_id, exc_info=True,
        )
        return None

    # 2. Recount. _count_prior_failures now includes the witness we
    # just wrote, so failure_count = total failures seen for workflow.
    failure_count = _count_prior_failures(workflow_id)
    if failure_count < 2:
        # Not yet a pattern — witness recorded but no pattern candidate.
        # Return None per spec: "1 次不生成".
        return None

    # 3. Threshold crossed: fire the pattern hook. The hook creates a
    # separate "task_failure_pattern" candidate (idempotent by
    # source_ref="workflow:X"), so repeated calls with the same
    # failure count don't spam the queue.
    try:
        from eduflow.memory.event_hooks import on_task_failure_pattern
    except ImportError:
        _log.warning("event_bridge: event_hooks unavailable")
        return None

    event_ctx = {
        "workflow_id": workflow_id,
        "failure_count": failure_count,
        "failure_reasons": reasons,
        "task_ids": ctx.get("task_ids") or [task_id],
    }
    return _call_hook(
        on_task_failure_pattern, event_ctx, label="task_lifecycle",
    )
