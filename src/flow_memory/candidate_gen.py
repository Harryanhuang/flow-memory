"""Candidate generation with automatic scope/kind/layer inference.

This module layers on top of :mod:`eduflow.memory.candidates` (raw CRUD)
and adds the *intelligence*: given an operational event context, infer
the right ``(scope, kind, layer)`` tuple and produce a candidate
without the caller having to know the memory taxonomy.

Public surface:
  - ``add_candidate`` / ``list_candidates`` / ``promote_candidate`` /
    ``reject_candidate`` / ``expire_stale_candidates`` — re-exported
    from ``candidates`` so callers can import everything from one place.
  - ``infer_scope_kind_layer(event_ctx)`` — pure inference helper,
    exposed for tests and for callers that want to preview the
    decision before creating anything.
  - ``generate_from_event(source_type, event_ctx, content, ...)`` —
    convenience: infer + create in one call.

Inference rules (``_infer_scope_kind_layer``)
---------------------------------------------
The taxonomy has three axes. Picking them right matters because a
``team``-scoped ``workflow_rule`` at ``core`` layer is injected into
every agent's context on every turn — over-scoping wastes attention,
under-scoping fails to protect. Defaults err toward narrow scope /
low layer so new candidates are conservative until promoted.

  source_type            → default (layer,        kind)
  review_reject          →   (episode,            mistake)
  closeout_anomaly       →   (decision,           workflow_rule)
  manager_correction     →   (decision,           workflow_rule)
                            ↑ layer→core if severity=high
  task_failure_pattern   →   (decision,           workflow_rule)

Scope resolution (in priority order):
  1. explicit ``scope`` in event_ctx  → use as-is
  2. task_id + workflow_id            → workflow:{workflow_id}
     …but for review_reject with repeated occurrences for the same
     workflow → lane:{workflow_id} (pattern indicates lane-wide issue)
  3. agent name, no workflow          → agent:{agent_name}
  4. workflow_id only                 → workflow:{workflow_id}
  5. fallthrough                      → team
"""
from __future__ import annotations

import logging
from typing import Any

from eduflow.memory.candidates import (
    add_candidate as _add_candidate,
    list_candidates as _list_candidates,
    promote_candidate as _promote_candidate,
    reject_candidate as _reject_candidate,
    expire_stale_candidates as _expire_stale_candidates,
    get_candidate,
)

_log = logging.getLogger(__name__)


# ── Re-exports ──────────────────────────────────────────────────────
# Why: event hooks and tests want one import site. The thin wrapper
# around add_candidate (generate_from_event) lives here; the raw CRUD
# stays in candidates.py so non-inferred callers don't pay for it.

add_candidate = _add_candidate
list_candidates = _list_candidates
promote_candidate = _promote_candidate
reject_candidate = _reject_candidate
expire_stale_candidates = _expire_stale_candidates


# ── Inference ─────────────────────────────────────────────────────

# Defaults per source_type: (layer, kind).
# These are *starting points* — explicit event_ctx overrides win.
_SOURCE_DEFAULTS: dict[str, tuple[str, str]] = {
    "review_reject": ("episode", "mistake"),
    "closeout_anomaly": ("decision", "workflow_rule"),
    "manager_correction": ("decision", "workflow_rule"),
    "task_failure_pattern": ("decision", "workflow_rule"),
    "manual": ("episode", "note"),
}

# Kinds that indicate a process flaw rather than a one-off error.
# When reject_reason mentions these signals, we upgrade kind from
# "mistake" to "workflow_rule" (the issue is structural, not personal).
_PROCESS_FLAW_SIGNALS = frozenset({
    "process", "procedure", "workflow", "flow",
    "missing step", "skipped", "handoff", "format",
    "template", "standard", "protocol",
})

# Phrases in reject_reason that indicate data integrity concerns.
_DATA_INTEGRITY_SIGNALS = frozenset({
    "mismatch", "inconsistent", "data", "count",
    "missing item", "manifest", "qtl", "qql",
})


def _infer_scope_kind_layer(
    source_type: str,
    event_ctx: dict[str, Any],
) -> tuple[str, str, str]:
    """Infer (scope, kind, layer) from an event context.

    Pure function — no DB access. Tests can exercise the decision
    surface without standing up SQLite.

    Returns (scope, kind, layer) where each value is a valid taxonomy
    token. When the event_ctx provides explicit overrides (``scope``,
    ``kind``, ``layer`` keys), those win over inference.
    """
    # Start from source_type defaults
    default_layer, default_kind = _SOURCE_DEFAULTS.get(
        source_type, ("episode", "note")
    )
    layer = default_layer
    kind = default_kind
    scope = "team"  # conservative fallback

    workflow_id = event_ctx.get("workflow_id", "")
    task_id = event_ctx.get("task_id", "")
    agent_name = (
        event_ctx.get("worker_name")
        or event_ctx.get("target_agent")
        or event_ctx.get("agent")
        or ""
    )

    # ── Scope resolution ──────────────────────────────────────────
    # 1. Explicit override wins.
    if event_ctx.get("scope"):
        scope = event_ctx["scope"]
    # 2. workflow + task → workflow:X (review_reject may upgrade to lane:X).
    elif workflow_id and task_id:
        scope = f"workflow:{workflow_id}"
        if source_type == "review_reject" and _is_recurring_review_reject(workflow_id):
            # Why upgrade to lane: a single reject is a worker mistake;
            # repeated rejects in the same workflow suggest the workflow
            # itself is broken (unclear instructions, missing checks).
            # lane: is broader than workflow: but narrower than team:.
            scope = f"lane:{workflow_id}"
    # 3. workflow only.
    elif workflow_id:
        scope = f"workflow:{workflow_id}"
    # 4. agent only (no workflow).
    elif agent_name:
        scope = f"agent:{agent_name}"
    # 5. task_id only → treat as workflow scope with task as id.
    elif task_id:
        scope = f"task:{task_id}"

    # ── Kind refinement ───────────────────────────────────────────
    # review_reject defaults to "mistake" (worker did wrong). If the
    # reason sounds structural, upgrade to workflow_rule (process
    # needs fixing, not the worker).
    if source_type == "review_reject":
        reason_text = str(
            event_ctx.get("reject_reason", "")
            or event_ctx.get("reason", "")
        ).lower()
        if any(sig in reason_text for sig in _PROCESS_FLAW_SIGNALS):
            kind = "workflow_rule"

    # manager_correction: severity=high → role_rule (this is a
    # fundamental expectation about the role, not a one-off fix).
    if source_type == "manager_correction":
        severity = str(event_ctx.get("severity", "")).lower()
        if severity in ("high", "critical"):
            kind = "role_rule"
            layer = "core"  # core rules are the non-negotiable ones

    # task_failure_pattern: if the dominant failure reason looks like
    # a worker error pattern, use mistake; otherwise workflow_rule.
    if source_type == "task_failure_pattern":
        reasons = event_ctx.get("failure_reasons") or []
        combined = " ".join(str(r) for r in reasons).lower()
        if any(sig in combined for sig in _PROCESS_FLAW_SIGNALS):
            kind = "workflow_rule"
        else:
            kind = "mistake"

    # ── Explicit overrides (last, so callers can fine-tune) ───────
    if event_ctx.get("kind"):
        kind = event_ctx["kind"]
    if event_ctx.get("layer"):
        layer = event_ctx["layer"]

    return scope, kind, layer


def _is_recurring_review_reject(workflow_id: str) -> bool:
    """True if there are ≥2 proposed review_reject candidates for this workflow.

    Used by _infer_scope_kind_layer to decide whether a review_reject
    should be scoped at workflow: (first occurrence) or lane: (pattern).
    Silently returns False on any DB error — inference must never crash
    the caller.
    """
    try:
        existing = _list_candidates(
            scope=f"workflow:{workflow_id}",
            source_type="review_reject",
            status="proposed",
            limit=100,
        )
        return len(existing) >= 2
    except Exception:
        return False


# ── Public: event → candidate ──────────────────────────────────────

def generate_from_event(
    source_type: str,
    event_ctx: dict[str, Any],
    content: str,
    *,
    source_ref: str = "",
    reason: str = "",
    evidence_refs: list[str] | None = None,
    risk_flags: list[str] | None = None,
    apply_admission_gate: bool = True,
) -> str | None:
    """Infer scope/kind/layer from ``event_ctx`` and create a candidate.

    Returns the candidate_id on success, or ``None`` if the event
    shouldn't produce a candidate (e.g. empty content, DB failure,
    or admission gate rejection).

    This is the function event hooks call after they've assembled
    their event_ctx. It wraps ``add_candidate`` with inference so
    hooks stay declarative.

    If ``apply_admission_gate`` is True (default), the candidate is
    scored against five dimensions and rejected if score < threshold.
    Set False to bypass (e.g. for high-priority manual candidates).
    """
    if not content or not content.strip():
        return None
    try:
        scope, kind, layer = _infer_scope_kind_layer(source_type, event_ctx)
    except Exception:
        _log.warning(
            "inference failed for source_type=%s event_ctx=%s",
            source_type, event_ctx, exc_info=True,
        )
        return None

    # V3 P2-1: admission gate scoring
    if apply_admission_gate:
        try:
            from eduflow.memory.admission import score_candidate, ADMISSION_THRESHOLD
            score_result = score_candidate(
                content=content,
                source_type=source_type,
                source_ref=source_ref,
                evidence_refs=evidence_refs or [],
                proposed_scope=scope,
                proposed_kind=kind,
                risk_flags=risk_flags,
            )
            if not score_result["passed"]:
                _log.info(
                    "candidate rejected by admission gate (score=%.2f): %s",
                    score_result["score"],
                    content[:80],
                )
                return None
        except Exception:
            _log.warning("admission gate failed; allowing candidate", exc_info=True)

    try:
        return _add_candidate(
            scope=scope,
            kind=kind,
            content=content,
            source_type=source_type,
            source_ref=source_ref,
            layer=layer,
            reason=reason,
            evidence_refs=evidence_refs,
            risk_flags=risk_flags,
        )
    except Exception:
        _log.warning(
            "failed to create candidate for source_type=%s source_ref=%s",
            source_type, source_ref, exc_info=True,
        )
        return None


# Expose inference for direct use (tests, preview).
infer_scope_kind_layer = _infer_scope_kind_layer
