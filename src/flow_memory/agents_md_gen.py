"""AGENTS.md auto-generation (V3 P3-2).

Clusters confirmed workflow_rules / role_rules / runtime_rules from
memory_items and produces a draft AGENTS.md document. Inspired by
Qoder's high-frequency-task → AGENTS.md evolution.

Default behavior:
  - dry_run=True: returns the draft as a string, no file written
  - dry_run=False: writes to the target path

Output structure:
  # AGENTS.md for <scope>
  ## Must Follow
  - [workflow_rule] <content>  (MI-xxx)
  ## Workflow Rules
  - ...
  ## Role Rules
  - ...
  ## Runtime Rules
  - ...
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from eduflow.memory.items import list_memories


def generate_agents_md(
    scope: str,
    *,
    kinds: list[str] | None = None,
    min_importance: int = 5,
    limit: int = 50,
) -> str:
    """Generate AGENTS.md draft markdown for the given scope.

    Args:
        scope: e.g. "team", "lane:course", "workflow:igcse-subject-launch"
        kinds: which memory kinds to include. Defaults to rule-like kinds.
        min_importance: minimum importance threshold.
        limit: max memories to include.

    Returns markdown text (draft AGENTS.md).
    """
    if kinds is None:
        kinds = ["workflow_rule", "role_rule", "runtime_rule", "decision"]

    memories = list_memories(scope=scope, status="confirmed", limit=limit * 4)
    memories = [m for m in memories if m.get("kind") in kinds]
    memories = [m for m in memories if (m.get("importance", 0) or 0) >= min_importance]

    if not memories:
        return f"# AGENTS.md for `{scope}`\n\n_No qualifying memories yet._\n"

    # Group by kind
    grouped: dict[str, list[dict]] = {k: [] for k in kinds}
    for m in memories:
        grouped.setdefault(m["kind"], []).append(m)

    # Sort within each group by importance desc
    for k in grouped:
        grouped[k].sort(key=lambda m: (m.get("importance", 0) or 0), reverse=True)

    # Build markdown
    lines: list[str] = []
    lines.append(f"# AGENTS.md for `{scope}`")
    lines.append("")
    lines.append(f"_Auto-generated from confirmed memories (min importance {min_importance})._")
    lines.append(f"_Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}_")
    lines.append("")

    # Section ordering: workflow_rule → role_rule → runtime_rule → decision
    section_titles = {
        "workflow_rule": "## Workflow Rules",
        "role_rule": "## Role Rules",
        "runtime_rule": "## Runtime Rules",
        "decision": "## Decisions",
    }

    # Must Follow section (high-importance only)
    must_follow = [m for m in memories if (m.get("importance", 0) or 0) >= 8]
    if must_follow:
        lines.append("## Must Follow (high importance)")
        lines.append("")
        for m in must_follow[:10]:
            content = m["content"].replace("\n", " ").strip()
            lines.append(f"- **[{m['kind']}]** {content} (id={m['id']}, imp={m.get('importance')})")
        lines.append("")

    for kind in ["workflow_rule", "role_rule", "runtime_rule", "decision"]:
        items = grouped.get(kind, [])
        if not items:
            continue
        lines.append(section_titles[kind])
        lines.append("")
        for m in items[:limit]:
            content = m["content"].replace("\n", " ").strip()
            lines.append(f"- {content} _(id={m['id']}, imp={m.get('importance')})_")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"_Total memories included: {len(memories)}_")
    lines.append("")
    lines.append("> **Note**: This is a generated draft. Review and curate before committing.")
    lines.append("> Pass `--write` to write to file; pass `--dry-run` (default) to preview only.")
    return "\n".join(lines)


def write_agents_md(
    scope: str,
    output_path: str | Path,
    *,
    kinds: list[str] | None = None,
    min_importance: int = 5,
    limit: int = 50,
    overwrite: bool = False,
) -> dict:
    """Generate and optionally write AGENTS.md to a file.

    Returns dict with content, written status, path.
    """
    content = generate_agents_md(
        scope, kinds=kinds, min_importance=min_importance, limit=limit,
    )

    out_path = Path(output_path)
    if out_path.exists() and not overwrite:
        return {
            "written": False,
            "skipped": True,
            "path": str(out_path),
            "content": content,
            "reason": "file exists; use --overwrite to overwrite",
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return {
        "written": True,
        "skipped": False,
        "path": str(out_path),
        "content": content,
    }