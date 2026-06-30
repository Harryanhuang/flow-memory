# Quickstart

## Install

```bash
pip install flow-memory

# With vector search support:
pip install flow-memory[vector]

# With MCP server:
pip install flow-memory[mcp]

# With Postgres backend:
pip install flow-memory[postgres]

# Everything:
pip install flow-memory[all]
```

## Initialize

```bash
# Default: SQLite at ~/.flow_memory/flow_memory.db
flow-memory init

# Custom location:
export FLOW_MEMORY_DB=/path/to/your/memory.db
flow-memory init
```

## Add Your First Memory

```bash
# Add a confirmed memory directly
flow-memory items add team workflow_rule "Always use plan mode before implementing" --importance 8

# Or add a candidate (requires review to confirm)
flow-memory candidate add team note "Lesson learned from this session: ..."

# Pin it to make it part of the curated core
flow-memory pin MI-20260630-001

# Promote a candidate
flow-memory promote CAND-20260630-001 --reviewer manager
```

## Search Memories

```bash
# Full-text search
flow-memory search "closeout conditions"

# Hybrid search (FTS + vector)
flow-memory search "closeout" --hybrid

# Search by subject (uses subject hierarchy)
flow-memory recall --subject ap-calculus-bc

# Search by scope
flow-memory search "manager" --scope team --kind role_rule
```

## MCP Server (Claude Code / Codex)

```json
// ~/.claude/config.json
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

Once configured, Claude Code can call tools like:
- `memory_search(query="closeout")`
- `memory_set_profile(key="output_language", value="bilingual")`
- `memory_sensitive_unlock(password="xxx")`

## Set a User Preference

```bash
flow-memory profile set output_language bilingual
flow-memory profile set review_style codex-7-round

# All agents share these preferences
flow-memory profile list
```

## Use Sensitive Data (Encrypted)

```bash
# One-time setup (with security questions for recovery)
flow-memory sensitive setup

# Unlock for 60 minutes
flow-memory sensitive unlock

# Store encrypted sensitive data
flow-memory sensitive add team api_key "sk-..."

# Lock immediately
flow-memory sensitive lock
```

## Daily Maintenance

```bash
# Run all maintenance (expire, budget, export)
flow-memory daily

# Or schedule with cron/launchd:
# 0 23 * * * flow-memory daily
```

## Next Steps

- [Backends](backends.md) — Switch to Postgres or file-based
- [MCP Server](mcp-server.md) — Full tool list
- [CLI Reference](cli.md) — All commands
- [API Reference](api.md) — Python API