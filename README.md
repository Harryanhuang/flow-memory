# Flow Memory

> A SQLite / Postgres / file-backed memory system for AI agents.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## What is Flow Memory?

Flow Memory is a standalone Python package that provides multi-agent memory
with hybrid search, user profiles, encrypted sensitive storage, and an
MCP server — all backed by your choice of storage backend.

Originally extracted from the [EduFlow Team](https://github.com/eduflow-team)
project, Flow Memory is designed to be:

- **Backend-agnostic** — SQLite (default), Postgres, or Markdown files
- **Agent-friendly** — MCP server exposes 23+ tools out of the box
- **Privacy-first** — AES-256-GCM encryption for sensitive data
- **Production-tested** — 250+ unit tests, used in production by EduFlow

## Features

| Feature | Description |
|---------|-------------|
| **Hybrid search** | FTS5 + Vector embeddings fused via RRF |
| **User profile** | Cross-agent habit/preference storage |
| **Sensitive data** | AES-256-GCM encryption with password + recovery questions |
| **Pin mechanism** | Curated core protected from budget eviction |
| **Confidence decay** | Auto-downrank unused memories |
| **Subject hierarchy** | Multi-level subject recall (AP Calculus → AP Math → STEM) |
| **Dual query** | Topic + workflow background retrieval |
| **Daily summary** | Short-term memory layer (30-day retention) |
| **Dashboard** | CLI visualization of memory health |
| **AGENTS.md generation** | Auto-cluster confirmed rules into docs |
| **Reflect** | Agent-driven memory reflection |
| **MCP server** | 23+ tools for Claude Code / Codex / Gemini |

## Quickstart

```bash
pip install flow-memory

# Set up storage
flow-memory init

# Search memories
flow-memory search "closeout conditions"

# Set a user preference
flow-memory profile set output_language bilingual

# Start MCP server (for Claude Code / Codex)
flow-memory mcp
```

## Backend Selection

```python
from flow_memory import use_backend

# SQLite (default)
use_backend("sqlite", db_path="~/.flow_memory/memory.db")

# Postgres
use_backend("postgres", url="postgresql://user:pass@localhost:5432/flow_memory")

# Markdown files (git-trackable vault)
use_backend("markdown", root="~/my-vault/memories")
```

## MCP Configuration (Claude Code)

```json
// ~/.claude/config.json
{
  "mcpServers": {
    "flow-memory": {
      "command": "python3",
      "args": ["-m", "flow_memory.mcp_server"],
      "env": { "FLOW_MEMORY_DB": "~/.flow_memory/memory.db" }
    }
  }
}
```

## Documentation

- [MCP Server Usage Guide](docs/mcp-server.md)
- [Multi-Backend Guide](docs/backends.md)
- [V2/V3 Features](docs/features.md)
- [Migration from EduFlow](docs/migration-from-eduflow.md)

## License

MIT — see [LICENSE](LICENSE).