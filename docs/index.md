# Flow Memory Documentation

## Quick Links

- [Quickstart](quickstart.md) — Get started in 5 minutes
- [Backends](backends.md) — SQLite, Postgres, Markdown files
- [MCP Server](mcp-server.md) — Expose to Claude Code / Codex
- [CLI Reference](cli.md) — All commands
- [API Reference](api.md) — Python API
- [Migration from EduFlow](migration-from-eduflow.md) — Existing users

## Architecture

Flow Memory is organized in layers:

```
flow_memory/
├── storage/           ← Storage backend abstraction
│   ├── paths.py      ← PathProvider (Path resolution)
│   ├── sql.py        ← StorageBackend (SQL)
│   └── vector.py     ← VectorBackend (LanceDB)
├── policy/            ← Customizable policies
│   ├── taxonomy.py   ← MemoryTaxonomy (layers, kinds)
│   └── promotion.py  ← PromotionPolicy (who can promote)
├── i18n/              ← Localization
│   └── templates.py  ← String templates
├── embeddings.py      ← Embedding providers (SiliconFlow, Dummy)
├── items.py           ← Memory CRUD
├── candidates.py      ← Candidate lifecycle
├── search.py          ← FTS5 + hybrid search
├── vector_store.py    ← Vector search (LanceDB)
├── packet.py          ← Memory packet assembly
├── inject.py          ← CLI/Hooks injection
├── sensitive.py       ← AES-256-GCM encrypted storage
├── user_profile.py    ← Cross-agent habits
├── decay.py           ← Confidence decay
├── consolidate.py     ← Memory dedup/merge
├── admission.py       ← Candidate scoring
├── daily_summary.py   ← Short-term memory
├── dashboard.py       ← Visualization
├── agents_md_gen.py   ← AGENTS.md generator
├── reflect.py         ← Reflect CLI
├── mcp_server.py      ← MCP server
└── cli.py             ← CLI entry point
```

## Why Flow Memory?

| Need | Solution |
|------|----------|
| Multi-agent memory | Lane/scope/tag system, cross-agent user profile |
| Hybrid search | FTS5 + LanceDB fused via RRF |
| Sensitive data | AES-256-GCM with password + recovery questions |
| Production-ready | 500+ unit tests, WAL mode, busy timeout |
| Plugin-friendly | Storage/Vector/PathProvider abstractions, customizable taxonomy |
| Multiple storage | SQLite / Postgres / Markdown files |
| MCP-native | 23+ tools for Claude Code / Codex |
| Multi-locale | i18n template system (English + Chinese) |

## Next Steps

- New to Flow Memory? Start with [Quickstart](quickstart.md)
- Coming from EduFlow? See [Migration Guide](migration-from-eduflow.md)
- Want to use as MCP server? See [MCP Server docs](mcp-server.md)
- Building a custom backend? See [Storage Backend API](api.md#storage)