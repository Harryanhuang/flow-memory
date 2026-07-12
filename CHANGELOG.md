# Changelog

All notable changes to Flow Memory will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-07-13

### Added
- Stable generic memory components ported from the EduFlow upgrade, including
  event hooks, event bridge, scope aliases, derivation, expiration, capsules,
  skill evolution, and usage instrumentation.

### Changed
- Published package metadata now points to the canonical GitHub repository.
- Releases use PyPI Trusted Publishing with short-lived OIDC credentials.

## [0.1.0] - 2026-06-30

### Added
- Initial alpha release extracted from EduFlow Team project
- **Storage backends**: SQLite (default), Postgres (placeholder), Markdown files
- **Vector backends**: LanceDB (default), with abstract `VectorBackend` interface
- **Path abstraction**: `PathProvider` ABC with `DefaultPathProvider` that reads
  `$FLOW_MEMORY_STATE_DIR` (fallback `$EDUFLOW_STATE_DIR` → `~/.flow_memory`)
- **Core memory model**: 11-table schema (memory_items, candidates, daily_summary,
  sensitive_config, sensitive_memory_items, user_profile, etc.)
- **Hybrid search**: FTS5 + vector fusion via Reciprocal Rank Fusion (RRF)
- **User profile**: cross-agent habit/preference storage
- **Sensitive data**: AES-256-GCM encryption with PBKDF2 password + recovery
  questions (3 questions, 2/3 required for reset)
- **V3 features**:
  - Pin mechanism (curated core protected from budget eviction)
  - Confidence decay (age + usage factors)
  - Subject hierarchy (AP → Math → STEM inheritance)
  - Dual query retrieval (topic + workflow background)
  - Daily summary short-term memory
  - Candidate admission gate (5-dimension scoring)
  - JIT pull helpers
  - Memory visualization dashboard
  - AGENTS.md auto-generation from confirmed rules
  - Reflect CLI for agent-driven memory submission
- **MCP server**: 23+ tools for Claude Code / Codex integration
- **CLI**: 25+ subcommands under `flow-memory` entry-point
- **i18n**: English + Chinese template system, expandable

### Changed
- Renamed from `eduflow.memory` to `flow_memory`
- Abstracted hardcoded `~/.eduflow/` paths via `PathProvider`
- Removed EduFlow-specific subject hierarchies (AP/IGCSE/A-Level moved to host)

### Security
- Default password is PBKDF2-HMAC-SHA256 with 480,000 iterations (OWASP-recommended)
- Sensitive memory uses AES-256-GCM with 12-byte nonce + 16-byte auth tag
- Audit log auto-redacts sensitive fields (password/answer/token)

### Migration Notes
EduFlow users can install flow-memory and migrate with zero code changes:
```bash
pip install flow-memory
export FLOW_MEMORY_DB=~/.eduflow/eduflow_memory.db
# All existing eduflow.memory.* imports continue to work via backwards-compat shim
```
