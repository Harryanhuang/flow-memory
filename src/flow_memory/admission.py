"""Admission gate scoring for memory candidates (V3 P2-1).

Five-dimension score determines whether a candidate passes the quality
threshold before entering the review pool.

Dimensions:
  - evidence_quality: has evidence_refs > 0
  - reusability: scope=team/lane > workflow > task
  - stability: source_type affects reliability
  - kind_weight: workflow_rule/role_rule > mistake/preference > note
  - conflict_penalty: penalize semantically similar to existing confirmed
"""
from __future__ import annotations

DIMENSION_WEIGHTS = {
    "evidence_quality": 0.25,
    "reusability": 0.20,
    "stability": 0.20,
    "kind_weight": 0.15,
    "conflict_penalty": 0.20,
}
ADMISSION_THRESHOLD = 0.5


def score_candidate(
    content: str,
    source_type: str,
    source_ref: str,
    evidence_refs: list[str],
    proposed_scope: str,
    proposed_kind: str,
    risk_flags: list[str] | None = None,
    similar_to_existing: bool = False,
) -> dict:
    """Score a candidate for admission to the review pool.

    Returns:
        {score: float, passed: bool, reasons: list[str], breakdown: dict}
    """
    risk_flags = risk_flags or []
    breakdown: dict[str, float] = {}

    # 1. evidence_quality
    if evidence_refs and len(evidence_refs) > 0:
        breakdown["evidence_quality"] = 0.8
    else:
        breakdown["evidence_quality"] = 0.2

    # 2. reusability (scope-based)
    if proposed_scope.startswith("team") or proposed_scope.startswith("lane"):
        breakdown["reusability"] = 1.0
    elif proposed_scope.startswith("workflow") or proposed_scope.startswith("subject") or proposed_scope.startswith("project"):
        breakdown["reusability"] = 0.7
    elif proposed_scope.startswith("task"):
        breakdown["reusability"] = 0.4
    else:
        breakdown["reusability"] = 0.5

    # 3. stability (source_type-based)
    stable_sources = {"review_reject", "manager_correction", "manual"}
    medium_sources = {"closeout_anomaly", "task_failure_pattern", "runtime_incident"}
    if source_type in stable_sources:
        breakdown["stability"] = 0.9
    elif source_type in medium_sources:
        breakdown["stability"] = 0.6
    else:
        breakdown["stability"] = 0.5

    # 4. kind_weight
    high_kinds = {"workflow_rule", "role_rule"}
    medium_kinds = {"mistake", "preference", "decision", "runtime_rule"}
    low_kinds = {"note", "domain_fact"}
    if proposed_kind in high_kinds:
        breakdown["kind_weight"] = 1.0
    elif proposed_kind in medium_kinds:
        breakdown["kind_weight"] = 0.8
    elif proposed_kind in low_kinds:
        breakdown["kind_weight"] = 0.3
    else:
        breakdown["kind_weight"] = 0.5

    # 5. conflict_penalty (negative contribution)
    if similar_to_existing:
        breakdown["conflict_penalty"] = -0.3
    else:
        breakdown["conflict_penalty"] = 0.0

    # Weighted sum
    total = sum(
        breakdown[dim] * weight
        for dim, weight in DIMENSION_WEIGHTS.items()
    )
    # Clamp to [0, 1]
    score = max(0.0, min(1.0, total))
    passed = score >= ADMISSION_THRESHOLD

    # Build reasons
    reasons: list[str] = []
    if breakdown["evidence_quality"] < 0.5:
        reasons.append("missing evidence_refs")
    if breakdown["reusability"] < 0.5:
        reasons.append(f"narrow scope: {proposed_scope}")
    if breakdown["stability"] < 0.5:
        reasons.append(f"unreliable source: {source_type}")
    if breakdown["kind_weight"] < 0.5:
        reasons.append(f"low-value kind: {proposed_kind}")
    if similar_to_existing:
        reasons.append("semantically similar to existing confirmed memory")
    if risk_flags:
        reasons.append(f"risk flags: {','.join(risk_flags[:3])}")

    return {
        "score": round(score, 3),
        "passed": passed,
        "reasons": reasons,
        "breakdown": {k: round(v, 3) for k, v in breakdown.items()},
    }