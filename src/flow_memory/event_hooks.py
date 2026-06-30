"""Event hooks: translate operational events into memory candidates.

Each ``on_*`` function is a thin adapter between one event source and
:func:`eduflow.memory.candidate_gen.generate_from_event`. Hooks are
intentionally small — their only jobs are:

  1. Pull the relevant fields out of the event context dict.
  2. Compose a human-readable ``content`` string (this is what a
     reviewer reads in the candidate queue).
  3. Pick sensible ``risk_flags`` for the event class.
  4. Hand off to ``generate_from_event`` for inference + persistence.

Hooks never raise: callers (task.py, watchdog, etc.) run in hot paths
and a failing hook must not abort the underlying operation. Errors
are logged and the hook returns ``None``.

Idempotency comes for free: :func:`add_candidate` de-dupes on
``(source_type, source_ref)``, so firing the same hook twice with
the same source_ref produces one candidate, not two.
"""
from __future__ import annotations

import logging
from typing import Any

from eduflow.memory.candidate_gen import generate_from_event

_log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────

def _truthy(v: Any) -> bool:
    """Return True for non-empty strings and non-zero numbers."""
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    return bool(v)


def _compose_evidence(*parts: str) -> list[str]:
    """Build evidence_refs list from non-empty parts.

    Why filter empties: JSON arrays with "" entries pollute Obsidian
    exports and add visual noise for reviewers.
    """
    return [p for p in parts if _truthy(p)]


# ── Hook: review rejected ────────────────────────────────────────

def on_review_rejected(event_ctx: dict[str, Any]) -> str | None:
    """Create a candidate when a review verdict is fail/rejected.

    Expected event_ctx keys:
      task_id        — required; becomes source_ref and content anchor
      worker_name    — optional; names who made the mistake
      reject_reason  — required; the reviewer's stated reason
      review_content — optional; quoted into evidence
      workflow_id    — optional; used by inference for scope

    Returns candidate_id on success, None on skip/error.
    """
    try:
        task_id = event_ctx.get("task_id", "")
        reject_reason = event_ctx.get("reject_reason", "")
        if not task_id or not reject_reason:
            # Without these, the candidate would be content-empty or
            # untraceable. Skip rather than pollute the queue.
            return None

        worker = event_ctx.get("worker_name", "")
        review_content = event_ctx.get("review_content", "")

        # Content: front-load the actionable fact (what failed and why).
        # Worker name is informational — reviewers can look it up.
        content = f"任务 {task_id} review 被拒：{reject_reason}"
        if worker:
            content += f"（worker: {worker}）"

        reason = f"review rejected: {reject_reason}"

        evidence = _compose_evidence(
            f"task:{task_id}",
            f"review:{task_id}",
            review_content,
        )

        # Risk flags: data integrity signals escalate the concern.
        # Why special-case this: manifest/QTL/QQL mismatches are
        # structural, not cosmetic, and can propagate downstream.
        risk_flags: list[str] = []
        reason_lower = reject_reason.lower()
        data_signals = {"mismatch", "inconsistent", "data", "manifest", "qtl", "qql"}
        if any(sig in reason_lower for sig in data_signals):
            risk_flags.append("data_integrity")

        return generate_from_event(
            source_type="review_reject",
            event_ctx=event_ctx,
            content=content,
            source_ref=f"task:{task_id}",
            reason=reason,
            evidence_refs=evidence,
            risk_flags=risk_flags,
        )
    except Exception:
        _log.warning("on_review_rejected failed for ctx=%s", event_ctx, exc_info=True)
        return None


# ── Hook: closeout anomaly ───────────────────────────────────────

def on_closeout_anomaly(event_ctx: dict[str, Any]) -> str | None:
    """Create a candidate when closeout validation finds a structural anomaly.

    Expected event_ctx keys:
      task_id        — required
      anomaly_type   — required; e.g. "items_mismatch", "missing_manifest"
      expected_value — optional; what closeout expected
      actual_value   — optional; what closeout actually found
      workflow_id    — required (for scope resolution)

    Returns candidate_id on success, None on skip/error.
    """
    try:
        task_id = event_ctx.get("task_id", "")
        anomaly_type = event_ctx.get("anomaly_type", "")
        workflow_id = event_ctx.get("workflow_id", "")
        if not task_id or not anomaly_type or not workflow_id:
            return None

        expected = event_ctx.get("expected_value", "")
        actual = event_ctx.get("actual_value", "")

        content = f"任务 {task_id} closeout 异常：{anomaly_type}"
        if expected or actual:
            content += f"（期望: {expected or 'N/A'}，实际: {actual or 'N/A'}）"

        reason = f"closeout anomaly: {anomaly_type}"
        evidence = _compose_evidence(
            f"task:{task_id}",
            f"workflow:{workflow_id}",
            f"anomaly:{anomaly_type}",
        )

        # Closeout anomalies always get the closeout_gate flag:
        # they indicate a gate that failed to catch the issue earlier.
        return generate_from_event(
            source_type="closeout_anomaly",
            event_ctx=event_ctx,
            content=content,
            source_ref=f"task:{task_id}",
            reason=reason,
            evidence_refs=evidence,
            risk_flags=["closeout_gate"],
        )
    except Exception:
        _log.warning("on_closeout_anomaly failed for ctx=%s", event_ctx, exc_info=True)
        return None


# ── Hook: manager correction ─────────────────────────────────────

def on_manager_correction(event_ctx: dict[str, Any]) -> str | None:
    """Create a candidate when a manager explicitly corrects an agent.

    Expected event_ctx keys:
      target_agent        — required; who was corrected
      correction_content  — required; the correction itself
      context             — optional; what prompted the correction
      severity            — optional; "high"/"critical" → core/role_rule

    Returns candidate_id on success, None on skip/error.
    """
    try:
        target_agent = event_ctx.get("target_agent", "")
        correction = event_ctx.get("correction_content", "")
        if not target_agent or not correction:
            return None

        context = event_ctx.get("context", "")
        severity = event_ctx.get("severity", "")

        content = f"Manager 纠正 {target_agent}：{correction}"
        if context:
            content += f"\n\n背景：{context}"

        # Reason truncated to 100 chars (DB reason column is advisory,
        # not a place for essays).
        reason = f"manager correction: {correction[:100]}"
        evidence = _compose_evidence(
            f"agent:{target_agent}",
            context,
        )
        risk_flags: list[str] = []
        if str(severity).lower() in ("high", "critical"):
            risk_flags.append("high_severity")

        return generate_from_event(
            source_type="manager_correction",
            event_ctx=event_ctx,
            content=content,
            source_ref=f"agent:{target_agent}",
            reason=reason,
            evidence_refs=evidence,
            risk_flags=risk_flags,
        )
    except Exception:
        _log.warning("on_manager_correction failed for ctx=%s", event_ctx, exc_info=True)
        return None


# ── Hook: task failure pattern ───────────────────────────────────

def on_task_failure_pattern(event_ctx: dict[str, Any]) -> str | None:
    """Create a candidate when a workflow shows repeated failures.

    Expected event_ctx keys:
      workflow_id     — required
      failure_count   — required; MUST be >= 2 to fire (a single
                        failure is handled by on_review_rejected)
      failure_reasons — optional list of strings
      task_ids        — optional list of failed task IDs

    Returns candidate_id on success, None on skip / below-threshold.
    """
    try:
        workflow_id = event_ctx.get("workflow_id", "")
        failure_count = event_ctx.get("failure_count", 0)
        if not workflow_id:
            return None
        # Why >= 2: a single failure is an incident; two or more is
        # a pattern worth encoding as memory. The threshold prevents
        # one-off transient errors from becoming permanent rules.
        try:
            failure_count = int(failure_count)
        except (TypeError, ValueError):
            failure_count = 0
        if failure_count < 2:
            return None

        reasons = event_ctx.get("failure_reasons") or []
        task_ids = event_ctx.get("task_ids") or []

        content = f"工作流 {workflow_id} 出现重复失败模式：{failure_count} 次失败"
        if reasons:
            reason_summary = "; ".join(str(r) for r in reasons[:3])
            content += f"\n主要原因：{reason_summary}"
        if task_ids:
            content += f"\n涉及任务：{', '.join(str(t) for t in task_ids[:5])}"

        reason = f"pattern detected: {failure_count} failures in {workflow_id}"
        evidence = _compose_evidence(
            f"workflow:{workflow_id}",
            *[f"task:{t}" for t in task_ids[:5]],
        )

        return generate_from_event(
            source_type="task_failure_pattern",
            event_ctx=event_ctx,
            content=content,
            source_ref=f"workflow:{workflow_id}",
            reason=reason,
            evidence_refs=evidence,
            risk_flags=["recurring_failure"],
        )
    except Exception:
        _log.warning("on_task_failure_pattern failed for ctx=%s", event_ctx, exc_info=True)
        return None
