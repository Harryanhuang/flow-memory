"""Tests for policy modules (taxonomy + promotion)."""
from __future__ import annotations

import pytest

from flow_memory.policy import (
    DefaultPromotionPolicy,
    MemoryTaxonomy,
    PromotionPolicy,
    get_policy,
    get_taxonomy,
    set_policy,
    set_taxonomy,
)
from flow_memory.policy.taxonomy import get_taxonomy as _get_taxonomy
from flow_memory.policy.promotion import get_policy as _get_policy


def test_default_taxonomy_includes_core_kinds():
    tax = get_taxonomy()
    assert "core" in tax.layers
    assert "workflow_rule" in tax.kinds
    assert "role_rule" in tax.kinds
    assert "candidate" in tax.item_statuses
    assert "confirmed" in tax.item_statuses


def test_default_taxonomy_high_impact_kinds():
    tax = get_taxonomy()
    assert "workflow_rule" in tax.high_impact_kinds
    assert "role_rule" in tax.high_impact_kinds
    assert "note" not in tax.high_impact_kinds


def test_set_custom_taxonomy():
    custom = MemoryTaxonomy(
        kinds=frozenset({"custom_kind"}),
        layers=frozenset({"custom_layer"}),
    )
    set_taxonomy(custom)
    assert "custom_kind" in get_taxonomy().kinds
    # Restore default
    set_taxonomy(MemoryTaxonomy())


def test_default_promotion_high_impact_requires_authorized():
    policy = DefaultPromotionPolicy()
    # High-impact kind, manager allowed
    assert policy.can_promote("workflow_rule", "team", "manager", True) is True
    # High-impact kind, random user not allowed
    assert policy.can_promote("workflow_rule", "team", "random_user", True) is False
    # Non-high-impact, any reviewer OK
    assert policy.can_promote("note", "team", "anybody", False) is True


def test_default_promotion_empty_reviewer_denied():
    policy = DefaultPromotionPolicy()
    assert policy.can_promote("workflow_rule", "team", "", True) is False
    assert policy.can_promote("note", "team", "", False) is False


def test_set_custom_promotion_policy():
    class AlwaysAllow(PromotionPolicy):
        def can_promote(self, kind, scope, reviewer, is_high_impact):
            return True

    set_policy(AlwaysAllow())
    assert get_policy().can_promote("workflow_rule", "team", "anyone", True) is True
    # Restore
    set_policy(DefaultPromotionPolicy())