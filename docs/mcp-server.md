# MCP Server

Flow Memory ships with an MCP (Model Context Protocol) server that exposes
23+ tools to any MCP-compatible client (Claude Code, Codex, etc.).

## Quick Configuration

### Claude Code

Edit `~/.claude/config.json`:

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

Restart Claude Code. The `memory_*` tools will appear.

### Codex

Edit `~/.codex/config.toml`:

```toml
[mcp_servers.flow-memory]
command = "python3"
args = ["-m", "flow_memory.mcp_server"]
env = { FLOW_MEMORY_DB = "~/.flow_memory/memory.db" }
```

### Other MCP Clients

Standard MCP JSON-RPC over stdio. The server listens on stdin and emits JSON-RPC messages on stdout.

## Tool Reference

### Memory CRUD (7 tools)

| Tool | Description |
|------|-------------|
| `memory_search(query, scope?, kind?, limit?)` | Full-text search confirmed memories |
| `memory_semantic_search(query, top_k?)` | Vector similarity search |
| `memory_get(memory_id)` | Fetch single memory |
| `memory_add_candidate(scope, kind, content, reason?, evidence_refs?)` | Propose a candidate |
| `memory_promote(candidate_id, reviewer?)` | Promote candidate to confirmed |
| `memory_reject(candidate_id, reason?)` | Reject candidate |
| `memory_list_candidates(scope?, status?, limit?)` | List candidates |

### User Profile (3 tools)

| Tool | Description |
|------|-------------|
| `memory_get_profile(key)` | Read a profile entry |
| `memory_set_profile(key, value, value_type?, confidence?)` | Write a profile entry |
| `memory_list_profile(prefix?, limit?)` | List profile entries |

### Sensitive Data (10 tools)

| Tool | Description |
|------|-------------|
| `memory_sensitive_setup(password, q1, a1, q2, a2, q3, a3)` | One-time setup |
| `memory_sensitive_unlock(password)` | Unlock for 60 minutes |
| `memory_sensitive_status()` | Check lock state |
| `memory_sensitive_lock()` | Immediate lock |
| `memory_sensitive_get(memory_id)` | Decrypt and read sensitive memory |
| `memory_sensitive_add(scope, kind, content, created_by?)` | Encrypt and store |
| `memory_sensitive_list(scope?, kind?, limit?)` | List without decrypting |
| `memory_sensitive_search(query, limit?)` | Search decrypted content |
| `memory_sensitive_delete(memory_id)` | Delete encrypted memory |
| `memory_sensitive_recover(a1, a2, a3, new_password)` | Reset via security questions |

### Other (3 tools)

| Tool | Description |
|------|-------------|
| `memory_assemble_packet(agent, task_id?)` | Preview memory packet |
| `memory_record_feedback(memory_id, feedback)` | Log feedback for audit |
| `memory_dashboard(days?)` | Render dashboard |

## Example Conversations

### Setting user preferences

```
You: "Remember I prefer bilingual output"

Claude: memory_set_profile(key="output_language", value="bilingual", confidence=1.0)
        ✓ Set profile: output_language = bilingual
```

### Searching past decisions

```
You: "What did we decide about closeout procedures?"

Claude: memory_search(query="closeout", limit=5)
        [fts+vec] MI-20260625-008 | workflow_rule | closeout 三件套一致...
        [fts] MI-20260625-007 | manager 错误用 durable memory 当 state...
```

### Storing sensitive credentials

```
You: "Save my API key sk-test-12345 to the encrypted store"

Claude: memory_sensitive_unlock(password="...")
        ✓ Unlocked for 60 min

        memory_sensitive_add(scope="team", kind="api_key", content="sk-test-12345")
        ✓ Encrypted: SM-20260630-001
```

## Troubleshooting

### Tools don't appear in Claude Code

1. Verify `flow-memory` is installed: `pip show flow-memory`
2. Test the server manually: `python3 -m flow_memory.mcp_server < /dev/null`
3. Check `~/.claude/config.json` syntax
4. Restart Claude Code

### Permission errors

The MCP server runs with the same permissions as the user. Make sure:
- The DB directory is writable
- The DB file path in env is correct

### Performance

- FTS5 search is fast (~1ms)
- Vector search is slow (~200ms without warmup, ~50ms warm)
- Hybrid search = max(FTS, vector) ≈ ~200ms total

For large vaults (>10k memories), consider the [vector] extra and tune
`FLOW_MEMORY_EMBEDDING_BATCH_SIZE`.