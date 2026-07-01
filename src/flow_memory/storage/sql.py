"""Storage backend abstraction for Flow Memory.

Provides a `StorageBackend` ABC with three implementations:
  - SqliteBackend (default)
  - PostgresBackend (optional, requires psycopg)
  - MarkdownBackend (filesystem-backed, git-trackable)
"""
from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from pathlib import Path


class StorageBackend(ABC):
    """Single seam between domain code and the underlying storage."""

    @abstractmethod
    def connect(self):
        """Return a connection-like object."""

    @abstractmethod
    def init_schema(self) -> None:
        """Create all tables / files if they don't exist."""

    @abstractmethod
    def db_size_bytes(self) -> int:
        """Return the storage footprint in bytes."""

    @abstractmethod
    def fts5_available(self) -> bool:
        """Whether FTS5 full-text search is supported."""

    @abstractmethod
    def dialect(self) -> str:
        """Return 'sqlite', 'postgres', or 'markdown'."""


class SqliteBackend(StorageBackend):
    """Owns the canonical 11-table schema in SQLite (WAL mode + per-thread cache)."""

    _SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS active_constraints (
        id TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        constraint_level TEXT NOT NULL,
        constraint_type TEXT NOT NULL,
        content TEXT NOT NULL,
        source_ref TEXT DEFAULT '',
        evidence_refs TEXT DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'active',
        enforcement TEXT NOT NULL DEFAULT 'prompt_only',
        injection_point TEXT DEFAULT 'send,reidentify,compact',
        valid_from TEXT NOT NULL,
        valid_until TEXT DEFAULT '',
        created_by TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS task_capsules (
        task_id TEXT PRIMARY KEY,
        workflow_id TEXT DEFAULT '',
        owner TEXT DEFAULT '',
        gate TEXT DEFAULT '',
        goal TEXT DEFAULT '',
        acceptance TEXT DEFAULT '',
        current_status TEXT DEFAULT '',
        decisions TEXT DEFAULT '[]',
        blockers TEXT DEFAULT '[]',
        next_action TEXT DEFAULT '',
        last_evidence_ref TEXT DEFAULT '',
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS memory_items (
        id              TEXT PRIMARY KEY,
        layer           TEXT NOT NULL,
        scope           TEXT NOT NULL,
        kind            TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'candidate',
        content         TEXT NOT NULL,
        summary         TEXT DEFAULT '',
        source_ref      TEXT DEFAULT '',
        source_agent    TEXT DEFAULT 'unknown',
        evidence_refs   TEXT DEFAULT '[]',
        confidence      REAL DEFAULT 1.0,
        importance      INTEGER DEFAULT 5,
        valid_from      TEXT NOT NULL,
        valid_until     TEXT DEFAULT '',
        created_by      TEXT DEFAULT '',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        supersedes      TEXT DEFAULT '',
        revision_of     TEXT DEFAULT '',
        metadata_json   TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS memory_scope_aliases (
        alias           TEXT PRIMARY KEY,
        target_scope    TEXT NOT NULL,
        kind_filter     TEXT DEFAULT '',
        active          INTEGER DEFAULT 1,
        created_at      TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS memory_candidates (
        candidate_id    TEXT PRIMARY KEY,
        source_type     TEXT NOT NULL,
        source_ref      TEXT DEFAULT '',
        source          TEXT DEFAULT 'unknown',
        proposed_layer  TEXT DEFAULT 'episode',
        proposed_scope  TEXT NOT NULL,
        proposed_kind   TEXT NOT NULL,
        content         TEXT NOT NULL,
        reason          TEXT DEFAULT '',
        evidence_refs   TEXT DEFAULT '[]',
        risk_flags      TEXT DEFAULT '[]',
        created_at      TEXT NOT NULL,
        review_status   TEXT NOT NULL DEFAULT 'proposed',
        reviewed_by     TEXT DEFAULT '',
        reviewed_at     TEXT DEFAULT '',
        expires_at      TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS memory_user_profile (
        key             TEXT PRIMARY KEY,
        value           TEXT NOT NULL,
        value_type      TEXT DEFAULT 'text',
        confidence      REAL DEFAULT 1.0,
        evidence_refs   TEXT DEFAULT '[]',
        updated_at      TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sensitive_config (
        id              TEXT PRIMARY KEY DEFAULT 'singleton',
        password_hash   TEXT NOT NULL,
        salt            TEXT NOT NULL,
        questions_json  TEXT NOT NULL,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sensitive_memory_items (
        id              TEXT PRIMARY KEY,
        scope           TEXT NOT NULL,
        kind            TEXT NOT NULL,
        encrypted_data  BLOB NOT NULL,
        nonce           BLOB NOT NULL,
        tag             BLOB NOT NULL,
        status          TEXT NOT NULL DEFAULT 'confirmed',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS agent_lane_bindings (
        agent TEXT NOT NULL,
        lane_id TEXT NOT NULL,
        role TEXT DEFAULT '',
        active INTEGER DEFAULT 1,
        valid_from TEXT NOT NULL,
        valid_until TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (agent, lane_id)
    );

    CREATE TABLE IF NOT EXISTS memory_links (
        from_id TEXT NOT NULL,
        to_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (from_id, to_id, relation)
    );

    CREATE TABLE IF NOT EXISTS memory_daily_summary (
        date            TEXT NOT NULL,
        agent           TEXT NOT NULL,
        summary         TEXT NOT NULL,
        key_decisions   TEXT DEFAULT '[]',
        open_questions  TEXT DEFAULT '[]',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        PRIMARY KEY (date, agent)
    );
    """

    _INDEXES = """
    CREATE INDEX IF NOT EXISTS idx_ac_scope ON active_constraints(scope);
    CREATE INDEX IF NOT EXISTS idx_ac_status ON active_constraints(status);
    CREATE INDEX IF NOT EXISTS idx_ac_level ON active_constraints(constraint_level);
    CREATE INDEX IF NOT EXISTS idx_mi_scope ON memory_items(scope);
    CREATE INDEX IF NOT EXISTS idx_mi_status ON memory_items(status);
    CREATE INDEX IF NOT EXISTS idx_mi_kind ON memory_items(kind);
    CREATE INDEX IF NOT EXISTS idx_mi_layer ON memory_items(layer);
    CREATE INDEX IF NOT EXISTS idx_msa_active ON memory_scope_aliases(active);
    CREATE INDEX IF NOT EXISTS idx_mc_status ON memory_candidates(review_status);
    CREATE INDEX IF NOT EXISTS idx_mc_scope ON memory_candidates(proposed_scope);
    CREATE INDEX IF NOT EXISTS idx_mup_updated ON memory_user_profile(updated_at);
    CREATE INDEX IF NOT EXISTS idx_smi_scope ON sensitive_memory_items(scope);
    CREATE INDEX IF NOT EXISTS idx_smi_status ON sensitive_memory_items(status);
    CREATE INDEX IF NOT EXISTS idx_alb_agent ON agent_lane_bindings(agent);
    CREATE INDEX IF NOT EXISTS idx_alb_lane ON agent_lane_bindings(lane_id);
    CREATE INDEX IF NOT EXISTS idx_alb_active ON agent_lane_bindings(active);
    CREATE INDEX IF NOT EXISTS idx_ml_from ON memory_links(from_id);
    CREATE INDEX IF NOT EXISTS idx_ml_to ON memory_links(to_id);
    CREATE INDEX IF NOT EXISTS idx_ml_relation ON memory_links(relation);
    CREATE INDEX IF NOT EXISTS idx_mds_agent ON memory_daily_summary(agent);
    CREATE INDEX IF NOT EXISTS idx_mds_created ON memory_daily_summary(created_at);
    """

    _MIGRATIONS = """
    ALTER TABLE memory_items ADD COLUMN pinned INTEGER DEFAULT 0;
    """

    _FTS_TABLE = """
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts
    USING fts5(content, summary, id UNINDEXED, tokenize='trigram');
    """

    def __init__(self, db_path: Path | None = None) -> None:
        from flow_memory.storage.paths import get_path_provider

        self._db_path = Path(db_path) if db_path else get_path_provider().memory_db_file()
        self._local = threading.local()

    def _get_conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        self._local.conn = conn
        return conn

    def connect(self):
        return self._get_conn()

    def init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(self._SCHEMA_SQL)
        conn.executescript(self._INDEXES)
        # Migrations (idempotent — each wrapped in try/except)
        for migration_sql in [
            "ALTER TABLE memory_items ADD COLUMN pinned INTEGER DEFAULT 0",
            "ALTER TABLE memory_items ADD COLUMN source_agent TEXT DEFAULT 'unknown'",
            "ALTER TABLE memory_candidates ADD COLUMN source TEXT DEFAULT 'unknown'",
        ]:
            try:
                conn.execute(migration_sql)
                conn.commit()
            except Exception:
                pass  # column already exists
        # FTS5 if available
        try:
            conn.executescript(self._FTS_TABLE)
            conn.commit()
        except Exception:
            pass
        conn.commit()

    def db_size_bytes(self) -> int:
        return self._db_path.stat().st_size if self._db_path.exists() else 0

    def fts5_available(self) -> bool:
        try:
            test_conn = sqlite3.connect(":memory:")
            test_conn.execute("CREATE VIRTUAL TABLE _test_fts USING fts5(content)")
            test_conn.close()
            return True
        except Exception:
            return False

    def dialect(self) -> str:
        return "sqlite"


class PostgresBackend(StorageBackend):
    """Postgres backend (placeholder — full implementation deferred).

    Requires `pip install flow-memory[postgres]`.
    """

    def __init__(self, url: str) -> None:
        self._url = url

    def connect(self):
        raise NotImplementedError(
            "PostgresBackend is a placeholder. Use SqliteBackend or implement the "
            "psycopg-based connection in flow_memory.storage.sql.PostgresBackend.connect()."
        )

    def init_schema(self) -> None:
        raise NotImplementedError

    def db_size_bytes(self) -> int:
        return 0

    def fts5_available(self) -> bool:
        return False  # Postgres uses tsvector instead

    def dialect(self) -> str:
        return "postgres"


class MarkdownBackend(StorageBackend):
    """Filesystem-backed storage: each memory = one .md file.

    Suitable for git-tracked Obsidian vaults. Indexes FTS via SQLite mirror
    (or in-memory FTS for small vaults).
    """

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            from flow_memory.storage.paths import get_path_provider
            root = get_path_provider().obsidian_root() / "flow_memory"
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_db = self._root / ".flow_memory_index.db"
        self._sqlite_mirror: SqliteBackend | None = None

    def _mirror(self) -> SqliteBackend:
        if self._sqlite_mirror is None:
            self._sqlite_mirror = SqliteBackend(self._index_db)
            self._sqlite_mirror.init_schema()
        return self._sqlite_mirror

    def connect(self):
        return self._mirror().connect()

    def init_schema(self) -> None:
        self._mirror().init_schema()

    def db_size_bytes(self) -> int:
        total = 0
        for f in self._root.rglob("*.md"):
            try:
                total += f.stat().st_size
            except OSError:
                pass
        if self._index_db.exists():
            total += self._index_db.stat().st_size
        return total

    def fts5_available(self) -> bool:
        return True  # via mirror

    def dialect(self) -> str:
        return "markdown"


# ── Module-level singleton ────────────────────────────────────────

_backend: StorageBackend | None = None


def get_backend() -> StorageBackend:
    """Return the active storage backend. Lazy-inits SqliteBackend."""
    global _backend
    if _backend is None:
        _backend = SqliteBackend()
        _backend.init_schema()
    return _backend


def use_backend(name: str, **kwargs) -> StorageBackend:
    """Switch the active storage backend.

    Args:
        name: "sqlite" | "postgres" | "markdown"
        **kwargs: backend-specific arguments

    Returns the new backend.
    """
    global _backend
    if name == "sqlite":
        db_path = kwargs.get("db_path")
        _backend = SqliteBackend(Path(db_path) if db_path else None)
    elif name == "postgres":
        url = kwargs.get("url") or kwargs.get("dsn")
        if not url:
            raise ValueError("Postgres backend requires url= or dsn=")
        _backend = PostgresBackend(url)
    elif name == "markdown":
        root = kwargs.get("root")
        _backend = MarkdownBackend(Path(root) if root else None)
    else:
        raise ValueError(f"unknown backend: {name!r}")
    _backend.init_schema()
    return _backend


def set_backend(backend: StorageBackend) -> None:
    """Replace the active backend (for tests)."""
    global _backend
    _backend = backend