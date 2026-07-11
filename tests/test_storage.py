"""Tests for storage backends."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from flow_memory.storage import (
    DefaultPathProvider,
    MarkdownBackend,
    PathProvider,
    PostgresBackend,
    SqliteBackend,
    StorageBackend,
    get_backend,
    use_backend,
)


def test_sqlite_backend_init_schema(tmp_db_path):
    backend = SqliteBackend(db_path=tmp_db_path)
    backend.init_schema()
    conn = backend.connect()
    # Should have all the tables
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "memory_items" in tables
    assert "memory_candidates" in tables
    assert "memory_user_profile" in tables
    assert "sensitive_config" in tables
    assert "sensitive_memory_items" in tables
    assert "memory_daily_summary" in tables


def test_sqlite_backend_db_size_bytes(tmp_db_path):
    backend = SqliteBackend(db_path=tmp_db_path)
    assert backend.db_size_bytes() == 0
    backend.init_schema()
    assert backend.db_size_bytes() > 0


def test_sqlite_backend_fts5_available(tmp_db_path):
    backend = SqliteBackend(db_path=tmp_db_path)
    backend.init_schema()
    assert backend.fts5_available() is True  # Python 3.14 has FTS5


def test_sqlite_backend_dialect():
    backend = SqliteBackend(db_path=Path("/tmp/test.db"))
    assert backend.dialect() == "sqlite"


def test_use_backend_sqlite(tmp_db_path):
    backend = use_backend("sqlite", db_path=tmp_db_path)
    assert isinstance(backend, SqliteBackend)
    assert backend.dialect() == "sqlite"
    # Use it
    conn = backend.connect()
    conn.execute("SELECT 1").fetchone()


def test_use_backend_unknown_raises():
    with pytest.raises(ValueError, match="unknown backend"):
        use_backend("redis")


def test_postgres_backend_placeholder():
    """PostgresBackend is a placeholder until psycopg is wired up."""
    backend = PostgresBackend("postgresql://localhost/test")
    assert backend.dialect() == "postgres"
    assert backend.db_size_bytes() == 0
    assert backend.fts5_available() is False
    with pytest.raises(NotImplementedError):
        backend.connect()


def test_markdown_backend_init_schema(tmp_path):
    root = tmp_path / "markdown_store"
    backend = MarkdownBackend(root=root)
    backend.init_schema()
    assert backend.dialect() == "markdown"
    assert root.exists()


def test_markdown_backend_db_size_bytes(tmp_path):
    root = tmp_path / "markdown_store"
    backend = MarkdownBackend(root=root)
    backend.init_schema()
    size = backend.db_size_bytes()
    assert size > 0  # Mirror DB has some bytes


def test_default_path_provider_uses_env():
    import os

    os.environ["FLOW_MEMORY_STATE_DIR"] = "/tmp/fm_test"
    provider = DefaultPathProvider()
    assert provider.memory_db_file() == Path("/tmp/fm_test/flow_memory.db")
    assert provider.vector_index_dir() == Path("/tmp/fm_test/vector_index")
    assert provider.audit_log_file() == Path("/tmp/fm_test/audit.log")
    del os.environ["FLOW_MEMORY_STATE_DIR"]


def test_default_path_provider_fallback_to_eduflow_env():
    """For backward-compat, EDUFLOW_STATE_DIR is honored if FLOW_MEMORY_STATE_DIR is unset."""
    import os

    os.environ.pop("FLOW_MEMORY_STATE_DIR", None)
    os.environ["EDUFLOW_STATE_DIR"] = "/tmp/eduflow_fallback"
    provider = DefaultPathProvider()
    assert "eduflow" in str(provider.memory_db_file())
    del os.environ["EDUFLOW_STATE_DIR"]


def test_default_path_provider_fallback_to_home():
    import os

    os.environ.pop("FLOW_MEMORY_STATE_DIR", None)
    os.environ.pop("EDUFLOW_STATE_DIR", None)
    provider = DefaultPathProvider()
    assert ".flow_memory" in str(provider.memory_db_file())


def test_default_path_provider_flow_memory_db_override():
    """FLOW_MEMORY_DB overrides the default state-dir-based DB path."""
    import os

    os.environ.pop("FLOW_MEMORY_STATE_DIR", None)
    os.environ.pop("EDUFLOW_STATE_DIR", None)
    os.environ["FLOW_MEMORY_DB"] = "/tmp/fm_custom.db"
    provider = DefaultPathProvider()
    assert provider.memory_db_file() == Path("/tmp/fm_custom.db")
    del os.environ["FLOW_MEMORY_DB"]


def test_get_backend_returns_default_when_none_set():
    backend = get_backend()
    assert isinstance(backend, SqliteBackend)