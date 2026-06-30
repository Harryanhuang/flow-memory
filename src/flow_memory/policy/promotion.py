"""Promotion policy for memory candidates.

By default, high-impact kinds require an authorized reviewer. Hosts can
customize who is allowed to promote what via `PromotionPolicy`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class PromotionPolicy(ABC):
    """Decide whether a given reviewer can promote a candidate."""

    @abstractmethod
    def can_promote(
        self,
        kind: str,
        scope: str,
        reviewer: str,
        is_high_impact: bool,
    ) -> bool:
        """Return True if `reviewer` is allowed to promote this candidate."""


class DefaultPromotionPolicy(PromotionPolicy):
    """Default policy: any non-empty reviewer can promote non-high-impact;
    high-impact requires reviewer in {manager, admin}."""

    AUTHORIZED_REVIEWERS = frozenset({"manager", "admin", "hermes"})

    def can_promote(
        self,
        kind: str,
        scope: str,
        reviewer: str,
        is_high_impact: bool,
    ) -> bool:
        if not reviewer or not reviewer.strip():
            return False
        if is_high_impact:
            return reviewer in self.AUTHORIZED_REVIEWERS
        return True


# ── Module-level singleton ────────────────────────────────────────

_policy: PromotionPolicy = DefaultPromotionPolicy()


def get_policy() -> PromotionPolicy:
    return policy


def set_policy(new_policy: PromotionPolicy) -> None:
    global policy
    policy = new_policy