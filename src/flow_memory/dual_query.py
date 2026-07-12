"""Dual query retrieval (V3 P1-4).

Combines two retrieval strategies:
  1. Topic query: search memories by task/agent context
  2. Background query: search memories by workflow_id / project_id / lane

Results are merged and deduplicated. This improves recall coverage by
combining semantic similarity (topic) with structural context (workflow).
"""

from __future__ import annotations


def dual_query_memories(
    topic_query: str,
    *,
    workflow_id: str | None = None,
    project_id: str | None = None,
    lane: str | None = None,
    scope: str | None = None,
    kind: str | None = None,
    status: str = "confirmed",
    limit: int = 20,
) -> list[dict]:
    """Dual query: topic search + background context search.

    Returns merged, deduplicated list of memory dicts, each annotated with
    "_source" indicating which query path it came from:
      - "topic": matched topic_query via FTS
      - "background": matched workflow/project scope
      - "both": matched both
    """
    from flow_memory.search import search_memories

    # Path 1: topic query
    topic_results = []
    if topic_query and topic_query.strip():
        topic_results = search_memories(
            topic_query,
            scope=scope or None,
            kind=kind or None,
            status=status or None,
            limit=limit,
        )

    # Path 2: workflow/project background (direct scope lookup, not FTS)
    background_results = []
    bg_scopes = []
    if workflow_id:
        bg_scopes.append(f"workflow:{workflow_id}")
    if project_id:
        bg_scopes.append(f"project:{project_id}")
    if lane:
        bg_scopes.append(f"lane:{lane}")

    if bg_scopes:
        from flow_memory.items import list_memories

        for bg_scope in bg_scopes:
            scope_items = list_memories(
                scope=bg_scope,
                kind=kind or None,
                status=status or None,
                limit=limit,
            )
            background_results.extend(scope_items)

    # Merge and dedupe by memory_id, preserving source annotation
    merged: dict[str, dict] = {}
    for m in topic_results:
        mid = m.get("id", "")
        if mid:
            d = dict(m)
            d["_source"] = "topic"
            merged[mid] = d

    for m in background_results:
        mid = m.get("id", "")
        if not mid:
            continue
        if mid in merged:
            merged[mid]["_source"] = "both"
        else:
            d = dict(m)
            d["_source"] = "background"
            merged[mid] = d

    # Sort: "both" first, then "topic", then "background"
    priority = {"both": 0, "topic": 1, "background": 2}
    result = sorted(
        merged.values(), key=lambda m: priority.get(m.get("_source", "background"), 99)
    )
    return result[:limit]
