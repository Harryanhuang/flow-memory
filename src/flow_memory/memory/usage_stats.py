"""Usage statistics for flow-memory (V3 instrumentation).

Lightweight JSONL append-only log of memory writes + reads, used to
understand which sources (codex, hermes, claude-code, manual) are
producing what kinds of memories.

Public API:
  - record_write(source, kind, scope, memory_id=None)
  - record_read(source, kind, scope)
  - get_usage_stats(days=7) -> dict
  - get_source_breakdown(days=7) -> dict

Usage log location: <state_dir>/usage.jsonl (one line per event).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flow_memory.storage.paths import get_path_provider


_EVENT_TYPES = {"write", "read"}


def _log_path() -> Path:
    """Return path to usage.jsonl (create parent dir lazily)."""
    state_dir = get_path_provider().memory_db_file().parent
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "usage.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detect_source() -> str:
    """Infer the calling source from environment."""
    return os.environ.get(
        "FLOW_MEMORY_CALLER",
        os.environ.get("FLOW_MEMORY_SOURCE", "unknown"),
    )


def _append_event(
    event_type: str, source: str, kind: str, scope: str, memory_id: str | None = None
) -> None:
    """Append one event line to the usage log. Best-effort, never raises."""
    if event_type not in _EVENT_TYPES:
        return
    record = {
        "ts": _now_iso(),
        "event": event_type,
        "source": source,
        "kind": kind,
        "scope": scope,
    }
    if memory_id is not None:
        record["memory_id"] = memory_id
    try:
        path = _log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # never crash the caller


def record_write(
    source: str | None = None,
    kind: str = "unknown",
    scope: str = "unknown",
    memory_id: str | None = None,
) -> None:
    """Record a memory write event (add, promote, pin, etc.)."""
    _append_event(
        "write",
        source or _detect_source(),
        kind,
        scope,
        memory_id,
    )


def record_read(
    source: str | None = None,
    kind: str = "unknown",
    scope: str = "unknown",
) -> None:
    """Record a memory read event (search, get, packet assembly, etc.)."""
    _append_event(
        "read",
        source or _detect_source(),
        kind,
        scope,
    )


def get_usage_stats(days: int = 7) -> dict:
    """Aggregate counts from the usage log over the last N days.

    Returns:
        {
            "window_days": int,
            "total_writes": int,
            "total_reads": int,
            "writes_by_source": {"codex": 5, "hermes": 12, ...},
            "writes_by_kind": {"workflow_rule": 8, ...},
            "reads_by_source": {"codex": 3, ...},
        }
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return _aggregate(cutoff, days)


def _aggregate(cutoff_iso: str, days: int) -> dict:
    path = _log_path()
    if not path.exists():
        return _empty_stats(days)

    writes_by_source: Counter = Counter()
    writes_by_kind: Counter = Counter()
    reads_by_source: Counter = Counter()
    total_writes = 0
    total_reads = 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("ts", "") < cutoff_iso:
                    continue
                event = rec.get("event", "")
                source = rec.get("source", "unknown")
                kind = rec.get("kind", "unknown")
                if event == "write":
                    total_writes += 1
                    writes_by_source[source] += 1
                    writes_by_kind[kind] += 1
                elif event == "read":
                    total_reads += 1
                    reads_by_source[source] += 1
    except Exception:
        return _empty_stats(days)

    return {
        "window_days": days,
        "total_writes": total_writes,
        "total_reads": total_reads,
        "writes_by_source": dict(writes_by_source.most_common()),
        "writes_by_kind": dict(writes_by_kind.most_common()),
        "reads_by_source": dict(reads_by_source.most_common()),
    }


def _empty_stats(days: int) -> dict:
    return {
        "window_days": days,
        "total_writes": 0,
        "total_reads": 0,
        "writes_by_source": {},
        "writes_by_kind": {},
        "reads_by_source": {},
    }


def render_stats_report(stats: dict) -> str:
    """Render usage stats as a human-readable report."""
    lines: list[str] = []
    lines.append(f"# 📊 Flow Memory Usage Stats ({stats['window_days']} days)")
    lines.append("")

    total_w = stats["total_writes"]
    total_r = stats["total_reads"]
    if total_w == 0 and total_r == 0:
        lines.append("_No usage events recorded yet._")
        lines.append("")
        lines.append("Events are written to `<state_dir>/usage.jsonl`.")
        lines.append(
            "Run any memory command (search, items add, etc.) to generate events."
        )
        return "\n".join(lines)

    lines.append(f"**Total writes**: {total_w}")
    lines.append(f"**Total reads**: {total_r}")
    lines.append("")

    if stats["writes_by_source"]:
        lines.append("## Writes by source")
        lines.append("")
        for source, count in stats["writes_by_source"].items():
            lines.append(f"  - {source}: {count}")
        lines.append("")

    if stats["writes_by_kind"]:
        lines.append("## Writes by kind")
        lines.append("")
        for kind, count in stats["writes_by_kind"].items():
            lines.append(f"  - {kind}: {count}")
        lines.append("")

    if stats["reads_by_source"]:
        lines.append("## Reads by source")
        lines.append("")
        for source, count in stats["reads_by_source"].items():
            lines.append(f"  - {source}: {count}")
        lines.append("")

    return "\n".join(lines)
