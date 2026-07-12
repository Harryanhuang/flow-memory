"""Flow Memory — A multi-backend memory system for AI agents.

Public API (importable as `from flow_memory import ...`):
  - assemble_memory_packet, extract_task_id_from_message (packet assembly)
  - add_memory, get_memory, list_memories, deprecate_memory, supersede_memory
  - pin_memory, unpin_memory, list_pinned_memories
  - add_candidate, list_candidates, promote_candidate, reject_candidate
  - search_memories, hybrid_search
  - search_similar, index_memory, remove_from_index (vector)
  - get_profile, set_profile, list_profile (user profile)
  - setup_password, unlock, lock, add_sensitive, get_sensitive, search_sensitive
  - upsert_summary, get_summary, list_summaries (daily summary)
  - render_dashboard, generate_agents_md, submit_reflection
  - use_backend, use_vector_backend (backend switching)

Storage backends:
  - SqliteBackend (default)
  - PostgresBackend (optional: pip install flow-memory[postgres])
  - MarkdownBackend (filesystem-backed, git-trackable)
"""

from flow_memory.storage import (
    DefaultPathProvider,
    LanceDBBackend,
    MarkdownBackend,
    PathProvider,
    PostgresBackend,
    SqliteBackend,
    StorageBackend,
    VectorBackend,
    get_backend,
    get_path_provider,
    get_vector_backend,
    set_backend,
    set_path_provider,
    use_backend,
    use_vector_backend,
)

__version__ = "0.1.1"

__all__ = [
    # Storage
    "StorageBackend",
    "SqliteBackend",
    "PostgresBackend",
    "MarkdownBackend",
    "VectorBackend",
    "LanceDBBackend",
    "PathProvider",
    "DefaultPathProvider",
    "get_backend",
    "get_path_provider",
    "get_vector_backend",
    "set_backend",
    "set_path_provider",
    "use_backend",
    "use_vector_backend",
]
