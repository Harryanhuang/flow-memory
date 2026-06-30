"""Runtime injection layer — inserts Memory Packets into message flows.

This module is the integration point between the memory system (which
stores constraints/capsules/memories) and the message flows that
deliver work to agents. Four injection sites are supported:

  ``send``       — manager → worker messages. Packet prepended so the
                   worker sees rules before the task.
  ``reidentify`` — agent wake prompt after /clear or context loss.
                   Packet appended so identity text comes first.
  ``compact``    — after the agent self-compacts its context. Packet
                   prepended so critical rules survive compression.
  ``gate_check`` — before a gate transition (closeout, phase change).
                   Returns a verdict; doesn't modify messages.

All functions are *pure* with respect to their inputs — they never
mutate the incoming string, only return a new one. When the packet
is empty (no relevant constraints/capsule/memories), the original
message is returned unchanged so callers can blindly pipe through
inject_to_send without conditional logic.

Backward compatibility: if the memory module fails to import (e.g.
running in a stripped-down environment), every function degrades to
a no-op pass-through. Gate check returns ``allowed=True`` (fail-open)
with a warning logged. This ensures memory-system failures cannot
take down the messaging pipeline.
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


# ── Packet formatting ─────────────────────────────────────────────

# These markers are deliberately noisy — they need to stand out in a
# stream of chat messages / prompt text so agents (and humans reading
# logs) can spot the injected block at a glance. Using `---[ ... ]---`
# rather than plain `---` avoids collision with markdown horizontal
# rules that agents commonly produce.
_PACKET_OPEN = "---[EduFlow Memory Packet]---"
_PACKET_OPEN_RECOVERY = "---[EduFlow Memory Packet - Recovery Context]---"
_PACKET_CLOSE = "---[End Memory Packet]---"


def _format_prepend(packet: str, message: str) -> str:
    """Wrap ``packet`` as a prepend block and attach to ``message``.

    Why blank-line-pad: LLMs reliably treat a blank line as a section
    boundary. Without it, the closing marker runs into the message
    body and the agent may misparse where the packet ends.
    """
    return (
        f"{_PACKET_OPEN}\n"
        f"{packet}\n"
        f"{_PACKET_CLOSE}\n"
        f"\n"
        f"{message}"
    )


def _format_append(message: str, packet: str) -> str:
    """Wrap ``packet`` as an appended recovery block."""
    return (
        f"{message}\n"
        f"\n"
        f"{_PACKET_OPEN_RECOVERY}\n"
        f"{packet}\n"
        f"{_PACKET_CLOSE}"
    )


def _assemble(agent: str, task_id: str | None, injection_point: str) -> str:
    """Thin wrapper around assemble_memory_packet with the right filter.

    Kept as a function (not inline) so the try/except import guard
    and the debug log live in one place. Returns "" if the memory
    module is unavailable — callers then degrade to pass-through.
    """
    try:
        from eduflow.memory.packet import assemble_memory_packet
    except ImportError:
        _log.debug("memory.packet unavailable; inject is pass-through")
        return ""
    try:
        packet = assemble_memory_packet(
            agent, task_id=task_id, injection_point=injection_point,
        )
        _log.debug(
            "inject assemble agent=%s task=%s point=%s len=%d",
            agent, task_id, injection_point, len(packet or ""),
        )
        return packet or ""
    except Exception:
        # Memory assembly must never crash the messaging pipeline.
        _log.warning(
            "inject assemble failed for agent=%s task=%s",
            agent, task_id, exc_info=True,
        )
        return ""


# ── Public API: injection functions ───────────────────────────────

def inject_to_send(agent: str, message: str) -> str:
    """Inject Memory Packet before a manager→worker message.

    Extracts task_id from the message (T-<digits>), builds a packet
    with constraints targeting the ``send`` injection point, and
    prepends it. Empty packet → original message unchanged.

    Pure function: ``message`` is not mutated.
    """
    if not message:
        return message
    try:
        from eduflow.memory.packet import extract_task_id_from_message
        task_id = extract_task_id_from_message(message)
    except ImportError:
        task_id = None
    packet = _assemble(agent, task_id, injection_point="send")
    if not packet:
        return message
    return _format_prepend(packet, message)


def inject_to_reidentify(
    agent: str,
    init_prompt: str,
    task_id: str | None = None,
) -> str:
    """Inject Memory Packet after a reidentify init prompt.

    Appended (not prepended) because the init prompt's identity
    instructions must be read first — the memory packet is context
    recovery, not identity. Empty packet → original prompt unchanged.
    """
    if not init_prompt:
        return init_prompt
    packet = _assemble(agent, task_id, injection_point="reidentify")
    if not packet:
        return init_prompt
    return _format_append(init_prompt, packet)


def inject_to_compact(
    agent: str,
    compacted_context: str,
    task_id: str | None = None,
) -> str:
    """Re-inject critical constraints after an agent self-compacts.

    /compact can drop constraints the agent was relying on. Prepending
    the packet puts them back at the top of the post-compact context
    where the agent will definitely see them on its next turn.
    """
    if not compacted_context:
        return compacted_context
    packet = _assemble(agent, task_id, injection_point="compact")
    if not packet:
        return compacted_context
    return _format_prepend(packet, compacted_context)


def build_gate_check(
    agent: str,
    task_id: str,
    gate_name: str,
) -> dict[str, Any]:
    """Check whether a gate transition is blocked by memory constraints.

    Returns a dict with:
      allowed:             bool — True if the gate can proceed.
      blocking_constraints: list[dict] — constraints that block.
      packet:              str — the assembled packet (for logging/audit).

    Fail-open: if the memory module is unavailable or any error
    occurs, returns ``allowed=True`` with an empty block list and a
    warning logged. Rationale: a memory-system outage should not
    freeze the entire workflow; the gate's existing non-memory
    checks (Package 1/3 derivation, verifier, etc.) still stand.

    Blocking rule: any active constraint with
      ``enforcement = 'gate_required'``
      AND ``constraint_level`` in {L0, L1}
      AND scope matching this agent/task
    blocks the gate. L2/L3 constraints are task-local and don't
    block structural gates.
    """
    empty_result: dict[str, Any] = {
        "allowed": True,
        "blocking_constraints": [],
        "packet": "",
    }
    try:
        from eduflow.memory.constraints import query_for_agent
        from eduflow.memory.packet import assemble_memory_packet
    except ImportError:
        _log.warning(
            "gate_check: memory module unavailable; fail-open "
            "agent=%s task=%s gate=%s",
            agent, task_id, gate_name,
        )
        return empty_result

    try:
        constraints = query_for_agent(agent, task_id=task_id)
    except Exception:
        _log.warning(
            "gate_check: query_for_agent failed; fail-open",
            exc_info=True,
        )
        return empty_result

    blocking: list[dict] = []
    for c in constraints:
        if c.get("enforcement") != "gate_required":
            continue
        level = c.get("constraint_level", "")
        if level not in ("L0", "L1"):
            # L2/L3 are task-scope; they inform but don't block
            # structural gates. Package 1/3 handle task-level gating
            # via derivation, not via this path.
            continue
        blocking.append({
            "id": c.get("id", ""),
            "level": level,
            "scope": c.get("scope", ""),
            "content": c.get("content", ""),
            "gate": gate_name,
        })

    try:
        packet = assemble_memory_packet(agent, task_id=task_id) or ""
    except Exception:
        packet = ""

    return {
        "allowed": len(blocking) == 0,
        "blocking_constraints": blocking,
        "packet": packet,
    }
