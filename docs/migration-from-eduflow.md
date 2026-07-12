# Migration from EduFlow

Flow Memory was extracted from the [EduFlow Team](https://github.com/eduflow-team)
project. This guide helps EduFlow users migrate to Flow Memory.

## TL;DR: Zero-Code Migration

If you have EduFlow installed, just:

```bash
pip install flow-memory
export FLOW_MEMORY_DB=/Users/huanganan/.eduflow/eduflow_memory.db
# Your existing `eduflow.memory.*` imports continue to work
```

Flow Memory ships with a backwards-compat shim that re-exports everything
from `flow_memory` under the old `eduflow.memory` namespace.

## Full Migration (Recommended)

For new code, prefer the `flow_memory` namespace directly:

| Old (EduFlow) | New (Flow Memory) |
|----------------|---------------------|
| `from eduflow.memory import items` | `from flow_memory import items` |
| `from eduflow.memory.db import get_conn` | `from flow_memory.storage import get_backend; backend.connect()` |
| `eduflow memory items add` | `flow-memory items add` |
| `eduflow memory profile list` | `flow-memory profile list` |
| `EDUFLOW_MEMORY_DB` env var | `FLOW_MEMORY_DB` env var |
| `~/.eduflow/eduflow_memory.db` | `~/.flow_memory/flow_memory.db` (or set `FLOW_MEMORY_DB`) |

## What Stays the Same

- All 11-table schema (`memory_items`, `candidates`, `sensitive_config`, etc.)
- All public API symbols (`add_memory`, `get_memory`, `pin_memory`, etc.)
- All CLI commands and their arguments
- All MCP server tools and their signatures
- All data already stored in your SQLite DB

## What's New in Flow Memory

| Feature | EduFlow | Flow Memory |
|---------|---------|-------------|
| Storage backends | SQLite only | SQLite / Postgres / Markdown files |
| Vector backends | LanceDB only | LanceDB + abstract `VectorBackend` interface |
| Path resolution | Hardcoded `~/.eduflow/` | `PathProvider` ABC + customizable |
| Taxonomy | Hardcoded frozensets | `MemoryTaxonomy` dataclass, customizable |
| Promotion policy | `{manager, hermes}` magic strings | `PromotionPolicy` ABC, customizable |
| i18n | Chinese hardcoded | `i18n` template system (en/zh/extensible) |
| Package | Sub-package of `eduflow` | Standalone PyPI package |

## Step-by-Step Migration

### Step 1: Install flow-memory

```bash
# Inside your EduFlow venv
cd EduFlow-Team-orch
source .venv/bin/activate
pip install flow-memory
```

Verify:
```bash
python -c "import flow_memory; print(flow_memory.__version__)"
# Output: 0.1.1
```

### Step 2: Point to existing DB

```bash
export FLOW_MEMORY_DB=/Users/huanganan/.eduflow/eduflow_memory.db
# Or add to .env / shell profile
```

### Step 3: Test your existing scripts

```bash
# These should still work without code changes
eduflow memory items list
eduflow memory daily
eduflow memory packet --agent worker_course
```

Internally, these now call flow_memory functions via the shim.

### Step 4: Gradual code migration (optional)

Over time, replace `eduflow.memory.*` with `flow_memory.*`:

```python
# Before
from eduflow.memory.items import add_memory
from eduflow.memory.candidates import promote_candidate
from eduflow.memory.user_profile import set_profile

# After
from flow_memory.items import add_memory
from flow_memory.candidates import promote_candidate
from flow_memory.user_profile import set_profile
```

### Step 5: Remove the shim (optional)

Once all callers have migrated:

```bash
# Delete the shim file
rm src/eduflow/memory/__init__.py

# Or keep as a thin re-export for backward compat:
# (file content becomes just the from flow_memory import *)
```

## What's NOT Migrated (Intentional)

Some files stay in EduFlow because they contain EduFlow-specific policy:

- `lane_bindings.py` — EduFlow's agent→lane routing (move to `eduflow.extensions`)
- Subject hierarchies (AP/IGCSE/A-Level) — EduFlow-specific curriculum data

Flow Memory core is generic. EduFlow adds its domain knowledge via extensions
and configuration.

## FAQ

### Q: My existing data is in `~/.eduflow/eduflow_memory.db`. Will Flow Memory read it?

A: Yes. Set `FLOW_MEMORY_DB=/Users/huanganan/.eduflow/eduflow_memory.db`
and Flow Memory will use that DB. No data migration needed.

### Q: Will my existing MCP server config still work?

A: Yes, but the recommended path is to switch to:
```json
{
  "mcpServers": {
    "flow-memory": {
      "command": "python3",
      "args": ["-m", "flow_memory.mcp_server"],
      "env": { "FLOW_MEMORY_DB": "..." }
    }
  }
}
```

### Q: Can I run flow_memory and eduflow.memory side-by-side?

A: Yes. Both write to the same DB (if paths match), so they're 100% compatible.
The shim ensures zero behavior change.

### Q: How do I switch from SQLite to Postgres?

```python
from flow_memory import use_backend

# Old: SQLite
# use_backend("sqlite", db_path="~/.flow_memory/memory.db")

# New: Postgres
use_backend("postgres", url="postgresql://user:pass@localhost:5432/flow_memory")
```

Existing data must be migrated with a one-time ETL (future feature;
for now, dump from SQLite and import to Postgres manually).

## Support

- GitHub: https://github.com/Harryanhuang/flow-memory/issues
- Docs: https://flow-memory.readthedocs.io (future)
- EduFlow compatibility: still maintained via shim
