"""Flow Memory MCP Server.

Exposes the memory subsystem as an MCP server so Claude Code, Codex, and other
MCP-capable agents can search, add, promote, and recall memories and user
preferences.

Run with:
    python -m flow_memory.mcp_server

Environment variables:
    FLOW_MEMORY_DB  -- override path to SQLite memory DB
"""
from __future__ import annotations

import json
from typing import Any

# FastMCP may not be installed if the optional [mcp] extra is missing.
# We import lazily and print a helpful error on startup.
try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _import_err:  # pragma: no cover
    FastMCP = None  # type: ignore

from flow_memory.storage import get_backend, get_path_provider

mcp: FastMCP | None = None
if FastMCP is not None:
    mcp = FastMCP("flow-memory")


def _init_db() -> None:
    """Ensure schema exists."""
    get_backend().init_schema()


def _to_json_safe(obj: Any) -> Any:
    """Convert sqlite3.Row / datetime to plain JSON-safe structures."""
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [_to_json_safe(v) for v in obj]
    return obj


def _load_json_field(value: str | None, default: Any = None) -> Any:
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default if default is not None else []


if mcp is not None:

    @mcp.tool()
    def memory_search(
        query: str,
        scope: str | None = None,
        kind: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search confirmed memory items."""
        _init_db()
        from flow_memory.search import search_memories

        results = search_memories(query, scope=scope, kind=kind, status="confirmed", limit=limit)
        return [_to_json_safe(r) for r in results]

    @mcp.tool()
    def memory_semantic_search(query: str, top_k: int = 5) -> list[dict]:
        """Semantic search over vector index (best-effort; returns [] if LanceDB unavailable)."""
        _init_db()
        try:
            from flow_memory.vector_store import search_similar

            results = search_similar(query, top_k=top_k)
            return [_to_json_safe(r) for r in results]
        except Exception:
            return []

    @mcp.tool()
    def memory_get(memory_id: str) -> dict | None:
        """Fetch a single memory item by ID."""
        _init_db()
        from flow_memory.items import get_memory

        row = get_memory(memory_id)
        return _to_json_safe(row) if row else None

    @mcp.tool()
    def memory_add_candidate(
        scope: str,
        kind: str,
        content: str,
        reason: str = "",
        evidence_refs: list[str] | None = None,
    ) -> dict:
        """Propose a new memory candidate for review."""
        _init_db()
        from flow_memory.candidates import add_candidate

        candidate_id = add_candidate(
            scope=scope,
            kind=kind,
            content=content,
            source_type="manual",
            reason=reason,
            evidence_refs=evidence_refs or [],
        )
        return {"candidate_id": candidate_id, "status": "proposed"}

    @mcp.tool()
    def memory_promote(candidate_id: str, reviewer: str = "") -> dict:
        """Promote a candidate to confirmed memory. High-impact kinds require authorized reviewer."""
        _init_db()
        from flow_memory.candidates import promote_candidate

        memory_id = promote_candidate(candidate_id, reviewer=reviewer)
        return {"memory_id": memory_id, "status": "confirmed"}

    @mcp.tool()
    def memory_reject(candidate_id: str, reason: str = "") -> dict:
        """Reject a memory candidate."""
        _init_db()
        from flow_memory.candidates import reject_candidate

        reject_candidate(candidate_id, reason=reason)
        return {"candidate_id": candidate_id, "status": "rejected"}

    @mcp.tool()
    def memory_list_candidates(
        scope: str | None = None,
        status: str = "proposed",
        limit: int = 50,
    ) -> list[dict]:
        """List memory candidates."""
        _init_db()
        from flow_memory.candidates import list_candidates

        results = list_candidates(scope=scope, status=status, limit=limit)
        return [_to_json_safe(r) for r in results]

    @mcp.tool()
    def memory_get_profile(key: str) -> dict | None:
        """Get a user profile entry."""
        _init_db()
        from flow_memory.user_profile import get_profile

        return _to_json_safe(get_profile(key))

    @mcp.tool()
    def memory_set_profile(
        key: str,
        value: str,
        value_type: str = "text",
        confidence: float = 1.0,
        evidence_refs: list[str] | None = None,
    ) -> dict:
        """Set a user profile entry (preference/habit)."""
        _init_db()
        from flow_memory.user_profile import set_profile

        # For MCP, value arrives as string; parse json/list if requested.
        parsed_value: Any = value
        if value_type == "json":
            parsed_value = json.loads(value)
        elif value_type == "list":
            parsed_value = json.loads(value) if value.startswith("[") else value.split(",")

        set_profile(
            key=key,
            value=parsed_value,
            value_type=value_type,
            confidence=confidence,
            evidence_refs=evidence_refs or [],
        )
        return {"key": key, "status": "set"}

    @mcp.tool()
    def memory_list_profile(prefix: str | None = None, limit: int = 100) -> list[dict]:
        """List user profile entries."""
        _init_db()
        from flow_memory.user_profile import list_profile

        results = list_profile(prefix=prefix, limit=limit)
        return [_to_json_safe(r) for r in results]

    @mcp.tool()
    def memory_assemble_packet(agent: str, task_id: str | None = None) -> str:
        """Assemble the markdown memory packet that would be injected for an agent."""
        _init_db()
        from flow_memory.packet import assemble_memory_packet

        return assemble_memory_packet(agent=agent, task_id=task_id)

    @mcp.tool()
    def memory_dashboard(days: int = 7) -> str:
        """Render memory health and activity for the requested time window."""
        _init_db()
        from flow_memory.dashboard import render_dashboard

        return render_dashboard(days=days)

    @mcp.tool()
    def memory_record_feedback(memory_id: str, feedback: str) -> dict:
        """Record free-form feedback about a memory for later audit/reflection."""
        _init_db()
        record = {
            "ts": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "action": "memory_feedback",
            "memory_id": memory_id,
            "feedback": feedback,
        }
        try:
            log_path = get_path_provider().audit_log_file()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return {"memory_id": memory_id, "status": "recorded"}

    # ── Sensitive data tools ────────────────────────────────────────

    @mcp.tool()
    def memory_sensitive_unlock(password: str) -> dict:
        """Unlock sensitive data access (60 minutes). Password stored as sensitive data."""
        _init_db()
        from flow_memory.sensitive import unlock
        return unlock(password)

    @mcp.tool()
    def memory_sensitive_status() -> dict:
        """Check sensitive data lock status."""
        _init_db()
        from flow_memory.sensitive import status
        return status()

    @mcp.tool()
    def memory_sensitive_lock() -> dict:
        """Immediately lock sensitive data."""
        _init_db()
        from flow_memory.sensitive import lock
        lock()
        return {"status": "locked"}

    @mcp.tool()
    def memory_sensitive_get(memory_id: str) -> dict | None:
        """Get a sensitive memory item (requires unlock)."""
        _init_db()
        from flow_memory.sensitive import get_sensitive
        return _to_json_safe(get_sensitive(memory_id))

    @mcp.tool()
    def memory_sensitive_add(
        scope: str,
        kind: str,
        content: str,
        created_by: str = "",
    ) -> dict:
        """Add a new sensitive memory item (encrypted, requires unlock)."""
        _init_db()
        from flow_memory.sensitive import add_sensitive
        memory_id = add_sensitive(
            scope=scope, kind=kind, content=content, created_by=created_by,
        )
        return {"memory_id": memory_id, "status": "encrypted"}

    @mcp.tool()
    def memory_sensitive_list(
        scope: str | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List sensitive memory items without decrypting content (requires unlock)."""
        _init_db()
        from flow_memory.sensitive import list_sensitive
        return [_to_json_safe(r) for r in list_sensitive(scope=scope, kind=kind, limit=limit)]

    @mcp.tool()
    def memory_sensitive_search(query: str, limit: int = 20) -> list[dict]:
        """Search sensitive memories by content (requires unlock)."""
        _init_db()
        from flow_memory.sensitive import search_sensitive
        return [_to_json_safe(r) for r in search_sensitive(query, limit=limit)]

    @mcp.tool()
    def memory_sensitive_delete(memory_id: str) -> dict:
        """Delete a sensitive memory item (requires unlock)."""
        _init_db()
        from flow_memory.sensitive import delete_sensitive
        ok = delete_sensitive(memory_id)
        return {"memory_id": memory_id, "deleted": ok}

    @mcp.tool()
    def memory_sensitive_setup(
        password: str,
        question1: str,
        answer1: str,
        question2: str,
        answer2: str,
        question3: str,
        answer3: str,
    ) -> dict:
        """Set up sensitive storage with password and 3 security questions."""
        _init_db()
        from flow_memory.sensitive import setup_password
        questions = [
            {"question": question1, "answer": answer1},
            {"question": question2, "answer": answer2},
            {"question": question3, "answer": answer3},
        ]
        setup_password(password, questions)
        return {"status": "configured", "questions": 3}

    @mcp.tool()
    def memory_sensitive_recover(
        answer1: str,
        answer2: str,
        answer3: str,
        new_password: str,
    ) -> dict:
        """Reset password using security questions (2 of 3 required)."""
        _init_db()
        from flow_memory.sensitive import recover
        answers = {"q0": answer1, "q1": answer2, "q2": answer3}
        recover(answers, new_password)
        return {"status": "recovered"}


def main() -> None:
    """Entry point for `python -m flow_memory.mcp_server`."""
    if mcp is None:
        print(
            "ERROR: 'mcp' package not installed. "
            "Install with: pip install 'flow-memory[mcp]'",
            file=__import__("sys").stderr,
        )
        raise SystemExit(1)

    mcp.run()


if __name__ == "__main__":
    main()
