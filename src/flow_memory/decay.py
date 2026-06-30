"""Confidence decay for memory items.

Computes a dynamic confidence value that decays with age and boosts with
recent usage. The decay is computed at read time (packet assembly, search
output) and never persisted directly — ``memory_items.confidence`` stays
as the base value; ``effective_confidence`` is derived on demand.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flow_memory.storage import get_backend


def effective_confidence(
    base_confidence: float,
    created_at: str,
    updated_at: str,
    now: str | None = None,
) -> float:
    """Compute dynamic confidence using age and usage factors.

    Args:
        base_confidence: Stored confidence (0.0-1.0).
        created_at: ISO timestamp when memory was created.
        updated_at: ISO timestamp of last touch/reference.
        now: ISO timestamp for "current time" (for testing).

    Returns:
        Float in [0.1, 1.0] = base × age_factor × usage_factor.

    Age factor:
        0-90d: 1.0, 90-180d: 0.9, 180-365d: 0.7, 365+d: 0.5

    Usage factor (based on updated_at):
        0-30d: 1.1, 30-90d: 1.0, 90+d: 0.85
    """
    if now is None:
        now = datetime.now(timezone.utc).isoformat()

    try:
        now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
        upd_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        # Normalize: if either is naive, treat as UTC
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        if upd_dt.tzinfo is None:
            upd_dt = upd_dt.replace(tzinfo=timezone.utc)
        days_since_update = (now_dt - upd_dt).days
    except (ValueError, AttributeError):
        return max(0.1, min(1.0, base_confidence))

    # Age factor (linear piecewise decay)
    if days_since_update <= 90:
        age_factor = 1.0
    elif days_since_update <= 180:
        age_factor = 0.9
    elif days_since_update <= 365:
        age_factor = 0.7
    else:
        age_factor = 0.5

    # Usage factor (boost if recently touched)
    if days_since_update <= 30:
        usage_factor = 1.1
    elif days_since_update <= 90:
        usage_factor = 1.0
    else:
        usage_factor = 0.85

    result = base_confidence * age_factor * usage_factor
    return max(0.1, min(1.0, result))


def touch_item(memory_id: str) -> None:
    """Update updated_at to current time without changing content or status.

    Used to mark a memory as recently referenced. Best-effort: never raises.
    """
    get_backend().init_schema()
    conn = get_backend().connect()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "UPDATE memory_items SET updated_at = ? WHERE id = ?",
            (now, memory_id),
        )
        conn.commit()
    except Exception:
        pass


def decay_batch(dry_run: bool = False) -> dict:
    """Batch-apply confidence decay to all confirmed memories.

    Returns counts: {total, updated, skipped}.
    If dry_run, reports what would change without writing.
    """
    get_backend().init_schema()
    conn = get_backend().connect()
    rows = conn.execute(
        "SELECT id, confidence, created_at, updated_at FROM memory_items WHERE status='confirmed'"
    ).fetchall()

    total = len(rows)
    updated = 0
    skipped = 0

    for row in rows:
        old_conf = float(row["confidence"] or 0.0)
        new_conf = effective_confidence(
            base_confidence=old_conf,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        # Only update if difference > 0.05 (avoid noise writes)
        if abs(new_conf - old_conf) > 0.05:
            if not dry_run:
                try:
                    conn.execute(
                        "UPDATE memory_items SET confidence = ? WHERE id = ?",
                        (new_conf, row["id"]),
                    )
                    updated += 1
                except Exception:
                    skipped += 1
            else:
                updated += 1
        else:
            skipped += 1

    if not dry_run:
        conn.commit()

    return {"total": total, "updated": updated, "skipped": skipped}