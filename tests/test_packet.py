"""Tests for flow_memory.packet read-only behavior."""

from __future__ import annotations

from flow_memory import items, packet


def test_assemble_packet_does_not_touch_items(fresh_backend):
    """Packet preview must not mutate memory updated_at timestamps."""
    mid = items.add_memory(scope="team", kind="note", content="x", status="confirmed")
    original = items.get_memory(mid)
    original_updated = original["updated_at"]

    packet.assemble_memory_packet("manager")

    refreshed = items.get_memory(mid)
    assert refreshed["updated_at"] == original_updated
