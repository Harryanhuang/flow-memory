"""flow-memory MCP server wrapper (Phase 3).

Re-exports the eduflow.memory.mcp_server as flow_memory.mcp_server so
the entry point `python -m flow_memory.mcp_server` works.

All write methods are instrumented via usage_stats.record_write to track
which source is creating which memories.
"""
from __future__ import annotations

import os

# Re-export the eduflow MCP server implementation (backwards-compat shim)
try:
    from eduflow.memory.mcp_server import (  # type: ignore[import-not-found]
        main,
    )
except ImportError:
    def main() -> int:
        print("ERROR: eduflow.memory.mcp_server not available", file=__import__("sys").stderr)
        print("Install eduflow or set PYTHONPATH to include its source.", file=__import__("sys").stderr)
        return 1


# Tag this process as the flow-memory MCP server
os.environ.setdefault("FLOW_MEMORY_CALLER", "mcp")

if __name__ == "__main__":
    import sys
    sys.exit(main())