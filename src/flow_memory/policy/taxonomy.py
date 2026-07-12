"""Memory taxonomy configuration.

Hosts can override the default taxonomy (layers, kinds, statuses) by
subclassing `MemoryTaxonomy` and passing the new instance to
`set_taxonomy()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MemoryTaxonomy:
    """Valid layers / kinds / statuses for memory items."""

    layers: frozenset = field(
        default_factory=lambda: frozenset(
            {
                "core",
                "task",
                "episode",
                "decision",
                "reflection",
                "archive",
            }
        )
    )
    kinds: frozenset = field(
        default_factory=lambda: frozenset(
            {
                "role_rule",
                "workflow_rule",
                "decision",
                "mistake",
                "preference",
                "handoff",
                "domain_fact",
                "runtime_rule",
                "note",
            }
        )
    )
    item_statuses: frozenset = field(
        default_factory=lambda: frozenset(
            {
                "candidate",
                "confirmed",
                "deprecated",
                "rejected",
            }
        )
    )
    high_impact_kinds: frozenset = field(
        default_factory=lambda: frozenset(
            {
                "workflow_rule",
                "role_rule",
                "runtime_rule",
                "decision",
                "preference",
                "handoff",
            }
        )
    )
    high_impact_expiry_days: int = 30
    default_expiry_days: int = 90


_default_taxonomy = MemoryTaxonomy()


def get_taxonomy() -> MemoryTaxonomy:
    """Return the active taxonomy (default if not overridden)."""
    return _default_taxonomy


def set_taxonomy(taxonomy: MemoryTaxonomy) -> None:
    """Replace the active taxonomy."""
    global _default_taxonomy
    _default_taxonomy = taxonomy
