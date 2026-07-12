"""Just-in-Time recall helpers (V3 P2-2).

When the packet is in push mode (default), only pinned + high-frequency
rules are auto-injected. All other memories are exposed via JIT pull
helpers that agents can call on demand.

This module provides:
  - get_recent_decisions: recent memory_items with kind=decision
  - get_mistakes_for_agent: mistakes scoped to agent or lane
  - get_handoffs: handoff memories for cross-agent context
  - get_facts_by_kind: get memories by kind on demand
"""

from __future__ import annotations

from flow_memory.items import list_memories


def get_recent_decisions(scope: str | None = None, limit: int = 10) -> list[dict]:
    """Recent decision memories. Used by JIT pull when agent needs to know 'why'."""
    return list_memories(
        kind="decision",
        scope=scope or None,
        status="confirmed",
        limit=limit,
    )


def get_mistakes_for_agent(
    agent: str | None = None,
    lane: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Mistake memories. Used by JIT pull when agent wants to avoid past failures."""
    scope: str | None = None
    if agent:
        scope = f"agent:{agent}"
    elif lane:
        scope = f"lane:{lane}"
    return list_memories(
        kind="mistake",
        scope=scope,
        status="confirmed",
        limit=limit,
    )


def get_handoffs(workflow_id: str | None = None, limit: int = 5) -> list[dict]:
    """Handoff memories. Used for cross-agent context passing."""
    scope = f"workflow:{workflow_id}" if workflow_id else None
    return list_memories(
        kind="handoff",
        scope=scope,
        status="confirmed",
        limit=limit,
    )


def get_facts_by_kind(
    kind: str, scope: str | None = None, limit: int = 10
) -> list[dict]:
    """Generic kind-based recall. Used for any kind not covered by specialized helpers."""
    return list_memories(
        kind=kind,
        scope=scope or None,
        status="confirmed",
        limit=limit,
    )
