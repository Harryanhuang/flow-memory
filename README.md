# Flow Memory

> A SQLite / Postgres / file-backed memory system for AI agents.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/Harryanhuang/flow-memory)](https://github.com/Harryanhuang/flow-memory/releases)
[![Tests](https://img.shields.io/badge/tests-533%20passing-brightgreen)](https://github.com/Harryanhuang/flow-memory)

## What is Flow Memory?

Flow Memory is a standalone Python package that provides multi-agent memory
with hybrid search, user profiles, encrypted sensitive storage, and an
MCP server — all backed by your choice of storage backend.

Originally extracted from the [EduFlow Team](https://github.com/eduflow-team)
project, Flow Memory is designed to be:

- **Backend-agnostic** — SQLite (default), Postgres, or Markdown files
- **Agent-friendly** — MCP server exposes 23+ tools out of the box
- **Privacy-first** — AES-256-GCM encryption for sensitive data
- **Production-tested** — 533 unit tests, used in production by EduFlow

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

---

## Installation

### Option 1: Install from GitHub (current)

PyPI release is pending. Install directly from the GitHub repo:

```bash
# Clone the repo
git clone https://github.com/Harryanhuang/flow-memory.git
cd flow-memory

# Create a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode (changes to source code take effect immediately)
pip install -e .

# Or install with extras
pip install -e ".[mcp]"       # + MCP server (Claude Code / Codex integration)
pip install -e ".[vector]"    # + LanceDB vector search
pip install -e ".[postgres]"  # + Postgres backend
pip install -e ".[all]"       # everything (recommended for development)
```

**Requirements**: Python 3.10+

### Option 2: Install from PyPI (when published)

```bash
pip install flow-memory
pip install flow-memory[mcp]      # + MCP server
pip install flow-memory[vector]   # + LanceDB
pip install flow-memory[all]      # everything
```

Track PyPI release: https://github.com/Harryanhuang/flow-memory/releases

---

## Quickstart

```bash
# Initialize storage (uses SQLite at ~/.flow_memory/memory.db by default)
flow-memory init

# Or specify a custom location
export FLOW_MEMORY_DB=/path/to/your/memory.db
flow-memory init

# Search memories
flow-memory search "closeout conditions"

# Set a user preference
flow-memory profile set output_language bilingual

# Add a confirmed memory
flow-memory items add team workflow_rule "Always use plan mode before implementing" --importance 8

# Start MCP server (for Claude Code / Codex)
flow-memory mcp
```

---

## MCP Configuration (Claude Code)

Add to `~/.claude/config.json`:

```json
{
  "mcpServers": {
    "flow-memory": {
      "command": "python3",
      "args": ["-m", "flow_memory.mcp_server"],
      "env": {
        "FLOW_MEMORY_DB": "~/.flow_memory/memory.db"
      }
    }
  }
}
```

Restart Claude Code. The 23 `memory_*` tools will appear in your tool list.

For Codex: `~/.codex/config.toml` with similar structure.

---

## Backend Selection

```python
from flow_memory import use_backend

# SQLite (default)
use_backend("sqlite", db_path="~/.flow_memory/memory.db")

# Postgres (requires pip install flow-memory[postgres])
use_backend("postgres", url="postgresql://user:pass@localhost:5432/flow_memory")

# Markdown files (git-trackable vault)
use_backend("markdown", root="~/my-vault/memories")
```

---

## CLI Quick Reference

```bash
# Memory CRUD
flow-memory items add team workflow_rule "..." --importance 8
flow-memory items list --scope team --kind workflow_rule
flow-memory items get MI-20260630-001

# Search
flow-memory search "closeout" --hybrid       # FTS + Vector
flow-memory search "closeout" --scope team   # scoped
flow-memory recall --subject ap-calc-bc       # subject hierarchy

# Pin / decay / consolidate (V3)
flow-memory pin MI-20260630-001
flow-memory pin list
flow-memory decay dry-run
flow-memory consolidate --report --threshold 0.85

# User profile
flow-memory profile list
flow-memory profile set output_language bilingual

# Sensitive data (encrypted)
flow-memory sensitive setup          # first time
flow-memory sensitive unlock          # 60 min
flow-memory sensitive add team api_key "sk-..."
flow-memory sensitive search "ssh"
flow-memory sensitive lock

# Daily summary
flow-memory daily-summary write worker_course "today's learnings"
flow-memory daily-summary list

# Dashboard
flow-memory dashboard --days 7

# AGENTS.md generation
flow-memory agents-md --scope team --write AGENTS.md

# Skill evolution
flow-memory skill-evolve report
flow-memory skill-evolve accept MI-...
flow-memory skill-evolve reject MI-...

# Daily maintenance
flow-memory daily
```

---

## Documentation

- [Quickstart Guide](docs/quickstart.md) — 5-minute setup
- [MCP Server Reference](docs/mcp-server.md) — All 23 tools documented
- [Migration from EduFlow](docs/migration-from-eduflow.md) — For EduFlow users
- [V3 Features](docs/v3-features.md) — Pin/decay/subject/dual-query/dashboard/agents-md/reflect
- [Architecture](docs/architecture.md) — How storage backends, vector backends, and policies compose

---

## Migration from EduFlow

If you're already using EduFlow's memory system:

```bash
# 1. Install flow-memory
pip install -e .            # from the cloned repo

# 2. Point to your existing DB
export FLOW_MEMORY_DB=/Users/you/.eduflow/eduflow_memory.db

# 3. All existing code works unchanged
# - `from eduflow.memory import ...` keeps working via shim
# - `eduflow memory ...` CLI keeps working
# - All 514 EduFlow tests pass without modification

# 4. Gradually migrate new code to flow_memory
# Old: from eduflow.memory.items import add_memory
# New: from flow_memory.items import add_memory
```

See [migration-from-eduflow.md](docs/migration-from-eduflow.md) for details.

---

## Project Status

| Component | Status |
|-----------|--------|
| Storage backends (SQLite / Postgres / Markdown) | ✅ |
| Vector backend (LanceDB) | ✅ |
| MCP server (23 tools) | ✅ |
| Hybrid search (FTS + Vector RRF) | ✅ |
| User profile (cross-agent habits) | ✅ |
| Sensitive data (AES-256-GCM) | ✅ |
| Pin mechanism (curated core) | ✅ |
| Confidence decay | ✅ |
| Subject hierarchy | ✅ |
| Dual query retrieval | ✅ |
| Daily summary (short-term memory) | ✅ |
| Admission gate scoring | ✅ |
| Dashboard visualization | ✅ |
| AGENTS.md auto-generation | ✅ |
| Reflect CLI | ✅ |
| Skill evolution skeleton | ✅ |
| CLI Native Memory integration | ⏸️ pending memory plugin spec |
| PyPI publication | ⏸️ pending maintainer setup |

---

## Contributing

Issues and PRs welcome: https://github.com/Harryanhuang/flow-memory/issues

Before submitting:
1. Run tests: `pytest tests/`
2. Run import check: `python scripts/check_imports.py` (must report clean)
3. Format: `ruff format src/ tests/`
4. Lint: `ruff check src/ tests/`

---

## Security

For vulnerability disclosures, see [SECURITY.md](SECURITY.md).

---

## License

MIT — see [LICENSE](LICENSE).