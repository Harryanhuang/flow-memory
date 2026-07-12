"""Storage abstraction layer for Flow Memory.

Exports:
  - PathProvider, DefaultPathProvider, get_path_provider, set_path_provider
  - StorageBackend, SqliteBackend, PostgresBackend, MarkdownBackend,
    get_backend, use_backend, set_backend
  - VectorBackend, LanceDBBackend, get_vector_backend, use_vector_backend
"""

from flow_memory.storage.paths import (
    DefaultPathProvider,
    PathProvider,
    get_path_provider,
    set_path_provider,
)
from flow_memory.storage.sql import (
    MarkdownBackend,
    PostgresBackend,
    SqliteBackend,
    StorageBackend,
    get_backend,
    set_backend,
    use_backend,
)
from flow_memory.storage.vector import (
    LanceDBBackend,
    VectorBackend,
    get_vector_backend,
    use_vector_backend,
)

__all__ = [
    # Paths
    "PathProvider",
    "DefaultPathProvider",
    "get_path_provider",
    "set_path_provider",
    # SQL
    "StorageBackend",
    "SqliteBackend",
    "PostgresBackend",
    "MarkdownBackend",
    "get_backend",
    "use_backend",
    "set_backend",
    # Vector
    "VectorBackend",
    "LanceDBBackend",
    "get_vector_backend",
    "use_vector_backend",
]
