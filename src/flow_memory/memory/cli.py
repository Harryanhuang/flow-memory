"""flow-memory CLI entry point (Phase 3 instrumentation).

Minimal CLI that wraps the existing eduflow memory_cli via the shim,
with one extra `stats` subcommand for usage instrumentation.
"""
from __future__ import annotations

import sys


def main() -> int:
    """Delegate to eduflow memory_cli.main with stats subcommand inserted."""
    # Intercept the `stats` subcommand before passing to eduflow
    if len(sys.argv) >= 2 and sys.argv[1] == "stats":
        return _run_stats(sys.argv[2:])

    # Fall through to eduflow memory_cli
    from eduflow.commands import memory_cli as eduflow_memory_cli
    return eduflow_memory_cli.main(sys.argv[1:])


def _run_stats(argv: list[str]) -> int:
    """Run `flow-memory stats [days]`."""
    days = 7
    for i, a in enumerate(argv):
        if a == "--days" and i + 1 < len(argv):
            try:
                days = int(argv[i + 1])
            except ValueError:
                print(f"Invalid --days value: {argv[i + 1]}")
                return 1
    from flow_memory.memory.usage_stats import get_usage_stats, render_stats_report
    stats = get_usage_stats(days=days)
    print(render_stats_report(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())