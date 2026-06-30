"""Memory Packet assembly and budget enforcement.

The Memory Packet is a compact markdown block prepended to messages (send)
or appended to init prompts (reidentify/compact) so workers retain critical
constraints after context loss.

Budget: constraints max 8 items (L0→L1→L2 priority), capsule max 800 chars,
memories max 5 items / 1000 chars, total ~4000 Chinese chars.
When over budget, drop from bottom — constraints are NEVER truncated.
"""
from __future__ import annotations

import json as _json
import re


# Hard budget
MAX_TOTAL_CHARS = 4000
MAX_CONSTRAINTS = 8
MAX_CAPSULE_CHARS = 800
MAX_MEMORIES = 5
MAX_MEMORY_CHARS = 1000


def _char_len(text: str) -> int:
    """Approximate Chinese char count (each CJK char ≈ 1 width)."""
    return len(text)


def _render_constraint(c: dict) -> str:
    """Render a single constraint as a markdown bullet."""
    level = c.get("constraint_level", "")
    enforcement = c.get("enforcement", "")
    content = c.get("content", "")
    tag = f"{level}/{enforcement}" if enforcement else level
    source = c.get("source_ref", "")
    source_suffix = f" ref={source}" if source else ""
    return f"- [{tag}] {content}{source_suffix}"


def _render_capsule(cap: dict) -> str:
    """Render a task capsule as a compact markdown block."""
    lines: list[str] = []
    task_id = cap.get("task_id", "")
    wf = cap.get("workflow_id", "")
    owner = cap.get("owner", "")
    gate = cap.get("gate", "")
    goal = cap.get("goal", "")
    status = cap.get("current_status", "")
    next_action = cap.get("next_action", "")
    blockers_raw = cap.get("blockers", "[]")
    acceptance = cap.get("acceptance", "")

    if isinstance(blockers_raw, str):
        try:
            blockers = _json.loads(blockers_raw)
        except Exception:
            blockers = []
    else:
        blockers = blockers_raw or []

    header = f"task: {task_id}"
    if wf:
        header += f" | workflow: {wf}"
    lines.append(f"- {header}")
    if owner:
        lines.append(f"- owner: {owner} | gate: {gate}")
    if goal:
        lines.append(f"- goal: {goal[:200]}")
    if next_action:
        lines.append(f"- next_action: {next_action}")
    if blockers:
        lines.append(f"- blockers: {', '.join(str(b) for b in blockers[:3])}")
    if acceptance:
        lines.append(f"- acceptance: {acceptance[:200]}")
    if status:
        lines.append(f"- status: {status}")

    return "\n".join(lines)


def _render_memories(agent: str, task_id: str | None) -> tuple[list[str], set[str]]:
    """Query confirmed memories relevant to agent scope, render markdown lines.

    V3 P0-1: applies effective_confidence (age + usage decay) for sorting.
    V3 P0-2: returns separate pinned / relevant segments.

    Returns (rendered_lines, memory_ids) where memory_ids is the set of IDs
    that contributed. The packet budget owns MAX_MEMORIES lines; semantic
    recall may supplement.
    """
    try:
        from flow_memory.items import list_memories, list_pinned_memories
        from flow_memory.scope_aliases import resolve_alias
        from flow_memory.decay import effective_confidence, touch_item
    except ImportError:
        return [], set()

    resolved_scope = resolve_alias(agent) if agent else None
    if not resolved_scope:
        resolved_scope = f"agent:{agent}" if agent else ""

    if not resolved_scope:
        return [], set()

    # V3 P0-2: pinned memories get a separate "curated core" segment.
    pinned_items = list_pinned_memories(scope=resolved_scope, limit=20)

    # Non-pinned memories for the "relevant" segment
    memories = list_memories(scope=resolved_scope, status="confirmed", limit=MAX_MEMORIES)

    # V3 P0-1: compute effective_confidence, sort by it descending
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    for m in memories:
        m["effective_confidence"] = effective_confidence(
            base_confidence=m.get("confidence", 1.0),
            created_at=m.get("created_at", now),
            updated_at=m.get("updated_at", now),
            now=now,
        )
    memories.sort(key=lambda m: (m.get("effective_confidence", 0), m.get("importance", 5)), reverse=True)

    lines: list[str] = []
    ids: set[str] = set()

    # Curated core (pinned, always present, no decay)
    if pinned_items:
        lines.append("### 📌 Curated Core (pinned)")
        for m in pinned_items:
            mid = m.get("id", "")
            kind = m.get("kind", "")
            summary = m.get("summary", "") or m.get("content", "")[:100]
            importance = m.get("importance", 5)
            lines.append(f"- [📌][{kind}] {summary} (importance={importance})")
            ids.add(mid)
            # V3 P0-1: touch to mark as recently used
            try:
                touch_item(mid)
            except Exception:
                pass

    # Relevant segment (decayed + sorted)
    if memories:
        lines.append("### Relevant Memories (decayed)")
        for m in memories:
            mid = m.get("id", "")
            if mid in ids:
                continue  # already in pinned
            kind = m.get("kind", "")
            summary = m.get("summary", "") or m.get("content", "")[:100]
            importance = m.get("importance", 5)
            eff = m.get("effective_confidence", 1.0)
            lines.append(f"- [{kind}] {summary} (eff_conf={eff:.2f}, importance={importance})")
            ids.add(mid)
            try:
                touch_item(mid)
            except Exception:
                pass

    return lines, ids


def _semantic_recall(
    agent: str,
    task_id: str | None,
    existing_memory_ids: set[str],
    budget_remaining: int,
) -> list[str]:
    """Supplement scope-matched memories with semantically similar ones.

    Returns up to 2 markdown lines for confirmed memories that were NOT
    already recalled by scope match.  The lines are lower priority than
    scope-matched memories and are the first to be dropped when budget
    is tight.
    """
    try:
        from flow_memory.vector_store import search_similar
    except ImportError:
        return []

    query_text = _build_semantic_query(agent, task_id)
    if not query_text:
        return []

    try:
        results = search_similar(query_text, top_k=5)
    except Exception:
        return []

    if not results:
        return []

    # Exclude already-recalled memories and sort by importance descending
    new_results = [
        r for r in results
        if r.get("memory_id", "") not in existing_memory_ids
    ]
    new_results.sort(key=lambda r: r.get("importance", 5), reverse=True)

    lines: list[str] = []
    total_chars = 0
    for r in new_results[:2]:
        kind = r.get("kind", "")
        content = r.get("content", "")
        summary = content[:100]
        importance = r.get("importance", 5)
        line = f"- [semantic][{kind}] {summary} (importance={importance})"
        line_len = _char_len(line)
        if budget_remaining - total_chars - line_len < 0:
            break
        lines.append(line)
        total_chars += line_len + 1  # +1 for newline

    return lines


def _dual_query_recall(
    agent: str,
    task_id: str | None,
    existing_memory_ids: set[str],
    budget_remaining: int,
) -> list[str]:
    """V3 P1-4: dual query (topic + workflow/project background).

    Returns up to 2 markdown lines for memories that were NOT already
    recalled by scope match. Source annotation: [topic], [background], [both].
    """
    try:
        from flow_memory.dual_query import dual_query_memories
    except ImportError:
        return []

    topic_query = _build_semantic_query(agent, task_id)
    if not topic_query:
        return []

    # Extract workflow_id / lane from task capsule
    workflow_id = None
    lane = None
    if task_id:
        try:
            from flow_memory.capsules import get_capsule
            cap = get_capsule(task_id)
            if cap:
                workflow_id = cap.get("workflow_id") or None
        except Exception:
            pass

    try:
        results = dual_query_memories(
            topic_query,
            workflow_id=workflow_id,
            lane=lane,
            limit=10,
        )
    except Exception:
        return []

    new_results = [r for r in results if r.get("id", "") not in existing_memory_ids]

    lines: list[str] = []
    total_chars = 0
    for r in new_results[:2]:
        kind = r.get("kind", "")
        source = r.get("_source", "topic")
        summary = (r.get("summary", "") or r.get("content", "")[:100])
        importance = r.get("importance", 5)
        line = f"- [dual:{source}][{kind}] {summary} (importance={importance})"
        line_len = _char_len(line)
        if budget_remaining - total_chars - line_len < 0:
            break
        lines.append(line)
        total_chars += line_len + 1

    return lines


def _build_semantic_query(agent: str, task_id: str | None) -> str:
    """Build a query string from capsule or agent context."""
    if task_id:
        try:
            from flow_memory.capsules import get_capsule
            cap = get_capsule(task_id)
            if cap:
                parts: list[str] = []
                if cap.get("goal"):
                    parts.append(cap.get("goal"))
                if cap.get("next_action"):
                    parts.append(cap.get("next_action"))
                if parts:
                    return " ".join(parts)
        except Exception:
            pass

    # No task_id or capsule: use agent identity + relevant constraint content
    query_parts: list[str] = [f"agent:{agent}"]
    try:
        from flow_memory.constraints import query_for_agent
        constraints = query_for_agent(agent, task_id=task_id)[:3]
        for c in constraints:
            content = c.get("content", "")
            if content:
                query_parts.append(content)
    except Exception:
        pass

    query = " ".join(query_parts)
    return query.strip()


def assemble_memory_packet(
    agent: str,
    task_id: str | None = None,
    *,
    max_chars: int = MAX_TOTAL_CHARS,
    injection_point: str | None = None,
) -> str:
    """Assemble a Memory Packet for the given agent.

    Returns markdown string or empty string if no constraints/capsules exist.

    When ``injection_point`` is set (e.g. "send", "reidentify", "compact"),
    only constraints targeting that injection site are included. Capsule
    and memories are unaffected — they carry task/memory context regardless
    of where the packet will be injected.
    """
    try:
        from flow_memory.constraints import query_for_agent
        from flow_memory.storage import get_backend
        from flow_memory.capsules import get_capsule, refresh_from_task_store
    except ImportError:
        return ""

    try:
        get_backend().init_schema()
    except Exception:
        return ""

    constraints = query_for_agent(
        agent, task_id=task_id, injection_point=injection_point,
    )[:MAX_CONSTRAINTS]
    capsule = None
    if task_id:
        capsule = get_capsule(task_id)
        if capsule is None:
            try:
                capsule = refresh_from_task_store(task_id)
            except Exception:
                pass

    # Section 3: Confirmed Memories (first to be truncated in budget)
    memory_lines, recalled_ids = _render_memories(agent, task_id)

    if not constraints and not capsule and not memory_lines:
        return ""

    sections: list[str] = []
    budget_remaining = max_chars

    # Section 1: Active Constraints (never truncated)
    if constraints:
        header = "## EduFlow Active Constraints\n"
        budget_remaining -= _char_len(header)
        l0_items: list[str] = []
        l1_items: list[str] = []
        l2_items: list[str] = []
        l3_items: list[str] = []
        for c in constraints:
            rendered = _render_constraint(c)
            level = c.get("constraint_level", "")
            if level == "L0":
                l0_items.append(rendered)
            elif level == "L1":
                l1_items.append(rendered)
            elif level == "L2":
                l2_items.append(rendered)
            else:
                l3_items.append(rendered)

        grouped = ""
        if l0_items:
            grouped += "### Must Follow (Team Rules)\n" + "\n".join(l0_items) + "\n\n"
        if l1_items:
            grouped += "### Workflow/Lane Rules\n" + "\n".join(l1_items) + "\n\n"
        if l2_items:
            grouped += "### Task Constraints\n" + "\n".join(l2_items) + "\n\n"
        if l3_items:
            grouped += "### Ephemeral Notes\n" + "\n".join(l3_items) + "\n\n"

        if not grouped:
            all_rendered = [_render_constraint(c) for c in constraints]
            grouped = "\n".join(all_rendered) + "\n\n"

        budget_remaining -= _char_len(grouped)
        sections.append(header + grouped)

    # Section 2: Task Capsule (capped at MAX_CAPSULE_CHARS)
    if capsule:
        cap_header = "### Current Task Capsule\n"
        cap_text = _render_capsule(capsule)
        if _char_len(cap_text) > MAX_CAPSULE_CHARS:
            cap_text = cap_text[:MAX_CAPSULE_CHARS] + "..."
        cap_section = cap_header + cap_text + "\n"
        budget_remaining -= _char_len(cap_section)
        sections.append(cap_section)

    # Section 3: Relevant Confirmed Memories (scope match first)
    semantic_lines: list[str] = []
    if budget_remaining > 0:
        semantic_lines = _semantic_recall(agent, task_id, recalled_ids, budget_remaining)

    # V3 P1-4: dual query (topic + workflow background)
    dual_lines: list[str] = []
    if budget_remaining > 0:
        dual_lines = _dual_query_recall(agent, task_id, recalled_ids, budget_remaining)

    all_memory_lines = memory_lines + semantic_lines + dual_lines
    if all_memory_lines:
        mem_header = "## Relevant Confirmed Memories\n"
        mem_text = "\n".join(all_memory_lines)
        # Enforce MAX_MEMORY_CHARS budget: drop dual/semantic first
        if _char_len(mem_text) > MAX_MEMORY_CHARS:
            while (dual_lines or semantic_lines) and _char_len(
                "\n".join(memory_lines + semantic_lines + dual_lines)
            ) > MAX_MEMORY_CHARS:
                if dual_lines:
                    dual_lines.pop()
                elif semantic_lines:
                    semantic_lines.pop()
            mem_text = "\n".join(memory_lines + semantic_lines + dual_lines)
            if _char_len(mem_text) > MAX_MEMORY_CHARS:
                mem_text = mem_text[:MAX_MEMORY_CHARS] + "..."
        mem_section = mem_header + mem_text + "\n"
        budget_remaining -= _char_len(mem_section)
        sections.append(mem_section)

    result = "".join(sections).rstrip()
    if not result:
        return ""

    # Hard budget enforcement: if over, truncate from bottom
    if _char_len(result) > max_chars:
        result = result[:max_chars] + "\n..."

    return result


def extract_task_id_from_message(message: str) -> str | None:
    """Try to extract a task ID (T-<n>) from a message string."""
    match = re.search(r'\b(T-\d+)\b', message)
    return match.group(1) if match else None
