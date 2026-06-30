"""Memory Scope Aliases — map agent names to target scopes.

Aliases allow agents to have persistent scope bindings that can be
resolved by other modules (e.g. packet.py, search.py) without
hardcoding agent→scope mappings.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flow_memory.storage import get_backend


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_alias(alias: str, target_scope: str, *, kind_filter: str = "") -> None:
    """Add or update a scope alias."""
    if not alias.strip():
        raise ValueError("alias cannot be empty")
    if not target_scope.strip():
        raise ValueError("target_scope cannot be empty")
    get_backend().init_schema()
    now = _now_iso()
    conn = get_backend().connect()
    conn.execute(
        """INSERT INTO memory_scope_aliases (alias, target_scope, kind_filter, active, created_at)
           VALUES (?, ?, ?, 1, ?)
           ON CONFLICT(alias) DO UPDATE SET target_scope=excluded.target_scope,
           kind_filter=excluded.kind_filter, active=1, created_at=excluded.created_at""",
        (alias.strip(), target_scope.strip(), kind_filter.strip(), now),
    )
    conn.commit()


def get_alias(alias: str) -> dict | None:
    """Fetch a single alias by name."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT * FROM memory_scope_aliases WHERE alias = ?", (alias,)
    ).fetchone()
    return dict(row) if row else None


def resolve_alias(alias: str) -> str | None:
    """Returns target_scope if alias is active, else None."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT target_scope, active FROM memory_scope_aliases WHERE alias = ?",
        (alias,),
    ).fetchone()
    if row is None or row["active"] != 1:
        return None
    return row["target_scope"]


def list_aliases(*, active_only: bool = True) -> list[dict]:
    """List all aliases, optionally filtering to active only."""
    get_backend().init_schema()
    conn = get_backend().connect()
    query = "SELECT * FROM memory_scope_aliases"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY alias"
    rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]


def deactivate_alias(alias: str) -> bool:
    """Set active=0 for an alias. Returns True if found and changed."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT active FROM memory_scope_aliases WHERE alias = ?", (alias,)
    ).fetchone()
    if row is None:
        return False
    if row["active"] == 0:
        return False
    conn.execute(
        "UPDATE memory_scope_aliases SET active = 0 WHERE alias = ?",
        (alias,),
    )
    conn.commit()
    return True


# ── V3 P0-3: Subject hierarchy ─────────────────────────────────────

# Static subject parent map (loaded at import). Format: child -> [parents...]
# Example: ap-calculus-bc -> [ap-math, ap-stem]
# In V3 production this should be configurable via CLI/DB, but v0.1 ships
# with a minimal default for AP curriculum subjects.
_SUBJECT_PARENTS: dict[str, list[str]] = {
    "ap-calculus-bc": ["ap-math", "ap-stem"],
    "ap-calculus-ab": ["ap-math", "ap-stem"],
    "ap-physics-1": ["ap-physics", "ap-stem"],
    "ap-physics-2": ["ap-physics", "ap-stem"],
    "ap-physics-c-mechanics": ["ap-physics", "ap-stem"],
    "ap-chemistry": ["ap-stem"],
    "ap-biology": ["ap-stem"],
    "ap-computer-science-a": ["ap-cs", "ap-stem"],
    "igcse-biology": ["igcse-science"],
    "igcse-chemistry": ["igcse-science"],
    "igcse-physics": ["igcse-science"],
    "igcse-mathematics": ["igcse-math"],
    "a-level-biology": ["a-level-science"],
    "a-level-chemistry": ["a-level-science"],
    "a-level-physics": ["a-level-science"],
    "a-level-mathematics": ["a-level-math"],
}


def get_subject_parents(subject: str) -> list[str]:
    """Return parent subjects for a given child subject (hierarchical inheritance).

    Example: get_subject_parents("ap-calculus-bc") -> ["ap-math", "ap-stem"]
    """
    return _SUBJECT_PARENTS.get(subject, [])


def get_subject_hierarchy(subject: str) -> list[str]:
    """Return full hierarchy from immediate to root: [child, parent1, parent2, ...].

    Example: get_subject_hierarchy("ap-calculus-bc") -> ["ap-calculus-bc", "ap-math", "ap-stem"]
    """
    hierarchy = [subject]
    visited = {subject}
    queue = [subject]
    while queue:
        current = queue.pop(0)
        for parent in _SUBJECT_PARENTS.get(current, []):
            if parent not in visited:
                visited.add(parent)
                hierarchy.append(parent)
                queue.append(parent)
    return hierarchy


def resolve_subject_scopes(subject: str) -> list[str]:
    """Return all scope strings that should match memories for a given subject.

    Returns ["subject:ap-calculus-bc", "subject:ap-math", "subject:ap-stem"] etc.
    Useful for cross-agent subject recall.
    """
    return [f"subject:{s}" for s in get_subject_hierarchy(subject)]


def add_subject_parent(child: str, parent: str) -> None:
    """Add a parent-child relationship at runtime."""
    parents = _SUBJECT_PARENTS.setdefault(child, [])
    if parent not in parents:
        parents.append(parent)


def list_subject_hierarchy() -> dict[str, list[str]]:
    """Return the full subject parent map."""
    return {k: list(v) for k, v in _SUBJECT_PARENTS.items()}
