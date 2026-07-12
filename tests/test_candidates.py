"""Tests for flow_memory.candidates generic helpers."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from flow_memory import candidates


def test_candidate_status_summary_counts_sources_and_kinds(fresh_backend):
    candidates.add_candidate(
        scope="team",
        kind="workflow_rule",
        content="Retry code-repair when same test fails twice",
        source_type="loop_repair_cycle",
        source_ref="loop:L-000001",
    )
    candidates.add_candidate(
        scope="team",
        kind="role_rule",
        content="Manager must approve high-risk handoffs",
        source_type="manual",
    )
    summary = candidates.candidate_status_summary()
    assert summary["total_proposed"] == 2
    assert summary["by_source_type"]["loop_repair_cycle"] == 1
    assert summary["by_source_type"]["manual"] == 1
    assert summary["by_kind"]["workflow_rule"] == 1
    assert summary["by_kind"]["role_rule"] == 1
    assert summary["high_impact"] == 2


def test_candidate_status_summary_flags_placeholder(fresh_backend):
    candidates.add_candidate(
        scope="team",
        kind="note",
        content="pin me",
        source_type="manual",
    )
    summary = candidates.candidate_status_summary()
    assert summary["placeholder_like"] == 1


def test_candidate_status_summary_counts_expiring_soon(fresh_backend):
    cid = candidates.add_candidate(
        scope="team",
        kind="note",
        content="Short-lived reminder",
        source_type="manual",
    )
    expires_soon = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    conn = fresh_backend.connect()
    conn.execute(
        "UPDATE memory_candidates SET expires_at = ? WHERE candidate_id = ?",
        (expires_soon, cid),
    )
    conn.commit()
    summary = candidates.candidate_status_summary()
    assert summary["expiring_within_7d"] == 1
