"""Shared pytest fixtures for flow_memory tests."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path):
    """Return a fresh temp DB path for each test."""
    return tmp_path / "test_memory.db"


@pytest.fixture
def fresh_backend(tmp_db_path, monkeypatch):
    """Return a freshly-initialized SqliteBackend bound to tmp path."""
    from flow_memory.storage import SqliteBackend

    backend = SqliteBackend(db_path=tmp_db_path)
    backend.init_schema()
    monkeypatch.setattr("flow_memory.storage._backend", backend)
    return backend


@pytest.fixture
def fresh_db_connection(fresh_backend):
    """Return a sqlite3 connection to the test DB."""
    return fresh_backend.connect()


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module-level singletons before/after each test."""
    import flow_memory.storage.sql as sql_mod
    import flow_memory.storage.paths as paths_mod
    import flow_memory.storage.vector as vec_mod

    for mod in (sql_mod, paths_mod, vec_mod):
        if hasattr(mod, "_backend"):
            mod._backend = None
        if hasattr(mod, "_provider"):
            mod._provider = None
        if hasattr(mod, "_vector"):
            mod._vector = None
    yield
    for mod in (sql_mod, paths_mod, vec_mod):
        if hasattr(mod, "_backend"):
            mod._backend = None
        if hasattr(mod, "_provider"):
            mod._provider = None
        if hasattr(mod, "_vector"):
            mod._vector = None