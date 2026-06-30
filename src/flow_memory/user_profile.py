"""User profile / cross-agent habit storage.

Stores user-level preferences and habits that should be injected into every
agent session, regardless of which agent is running. All values are strings;
structured data (lists/maps) is serialized as JSON with value_type='json'.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flow_memory.storage import get_backend

_VALID_VALUE_TYPES = frozenset({"text", "json", "list"})
_MAX_KEY_LEN = 128


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(value, value_type: str) -> str:
    if value_type == "text":
        return str(value)
    if value_type in ("json", "list"):
        return json.dumps(value, ensure_ascii=False)
    raise ValueError(f"unsupported value_type: {value_type}")


def _deserialize(raw: str, value_type: str):
    if value_type == "text":
        return raw
    if value_type in ("json", "list"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid json for value_type={value_type}: {exc}")
    raise ValueError(f"unsupported value_type: {value_type}")


def set_profile(
    key: str,
    value,
    *,
    value_type: str = "text",
    confidence: float = 1.0,
    evidence_refs: list[str] | None = None,
) -> None:
    """Set a user profile entry. Overwrites existing value."""
    if not key or len(key) > _MAX_KEY_LEN:
        raise ValueError(f"key must be 1-{_MAX_KEY_LEN} chars")
    if value_type not in _VALID_VALUE_TYPES:
        raise ValueError(f"invalid value_type: {value_type} (valid: {sorted(_VALID_VALUE_TYPES)})")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be 0.0-1.0, got {confidence}")

    get_backend().init_schema()
    serialized = _serialize(value, value_type)
    now = _now_iso()
    conn = get_backend().connect()
    conn.execute(
        """INSERT INTO memory_user_profile (key, value, value_type, confidence, evidence_refs, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET
             value=excluded.value,
             value_type=excluded.value_type,
             confidence=excluded.confidence,
             evidence_refs=excluded.evidence_refs,
             updated_at=excluded.updated_at""",
        (key, serialized, value_type, confidence, json.dumps(evidence_refs or []), now),
    )
    conn.commit()


def get_profile(key: str) -> dict | None:
    """Fetch a single user profile entry by key."""
    get_backend().init_schema()
    conn = get_backend().connect()
    row = conn.execute(
        "SELECT key, value, value_type, confidence, evidence_refs, updated_at "
        "FROM memory_user_profile WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    return {
        "key": row["key"],
        "value": _deserialize(row["value"], row["value_type"]),
        "value_type": row["value_type"],
        "confidence": row["confidence"],
        "evidence_refs": json.loads(row["evidence_refs"] or "[]"),
        "updated_at": row["updated_at"],
    }


def list_profile(prefix: str | None = None, limit: int = 100) -> list[dict]:
    """List user profile entries, optionally filtered by key prefix."""
    get_backend().init_schema()
    conn = get_backend().connect()
    query = (
        "SELECT key, value, value_type, confidence, evidence_refs, updated_at "
        "FROM memory_user_profile WHERE 1=1"
    )
    params: list = []
    if prefix:
        query += " AND key LIKE ?"
        params.append(f"{prefix}%")
    query += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [
        {
            "key": r["key"],
            "value": _deserialize(r["value"], r["value_type"]),
            "value_type": r["value_type"],
            "confidence": r["confidence"],
            "evidence_refs": json.loads(r["evidence_refs"] or "[]"),
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def delete_profile(key: str) -> bool:
    """Delete a user profile entry. Returns True if it existed."""
    get_backend().init_schema()
    conn = get_backend().connect()
    cur = conn.execute("DELETE FROM memory_user_profile WHERE key = ?", (key,))
    conn.commit()
    return cur.rowcount > 0


def render_profile_block(max_chars: int = 300) -> str:
    """Render the highest-confidence profile entries as a markdown block.

    Drops lowest-confidence entries if the rendered block would exceed max_chars.
    """
    entries = list_profile()
    if not entries:
        return ""

    lines: list[str] = ["## User Preferences"]
    total = len(lines[0]) + 1  # +1 for newline
    kept: list[dict] = []

    # Sort by confidence desc, then recency
    entries.sort(key=lambda e: (e["confidence"], e["updated_at"]), reverse=True)

    for entry in entries:
        value = entry["value"]
        if isinstance(value, list):
            value_str = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            value_str = json.dumps(value, ensure_ascii=False)
        else:
            value_str = str(value)
        line = f"- {entry['key']}: {value_str}"
        line_len = len(line) + 1
        if total + line_len > max_chars:
            break
        kept.append(entry)
        lines.append(line)
        total += line_len

    if len(lines) == 1:
        return ""  # only header, no entries fit
    return "\n".join(lines)
