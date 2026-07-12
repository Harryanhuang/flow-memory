"""Path resolution abstraction for Flow Memory.

Provides a `PathProvider` ABC and `DefaultPathProvider` that resolves all
on-disk locations used by the memory subsystem. Hosts can override to
customize storage layout (e.g. point DB at /var/lib/flow-memory, vector
index at a different mount, etc.).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path


class PathProvider(ABC):
    """Resolves every on-disk location the memory subsystem touches."""

    @abstractmethod
    def memory_db_file(self) -> Path:
        """Path to the primary memory database (SQLite or pg socket)."""

    @abstractmethod
    def vector_index_dir(self) -> Path:
        """Directory for vector index files (LanceDB, etc.)."""

    @abstractmethod
    def audit_log_file(self) -> Path:
        """JSONL audit log path."""

    @abstractmethod
    def export_log_file(self) -> Path:
        """Export operation log path."""

    @abstractmethod
    def obsidian_root(self) -> Path:
        """Default Obsidian vault root for exporters."""

    def ensure_state(self) -> None:
        """Create parent directories for all paths. Default implementation."""
        for path_method in (
            self.memory_db_file,
            self.vector_index_dir,
            self.audit_log_file,
            self.export_log_file,
            self.obsidian_root,
        ):
            try:
                p = path_method()
                if hasattr(p, "parent"):
                    p.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass


class DefaultPathProvider(PathProvider):
    """Resolves paths under $FLOW_MEMORY_STATE_DIR (fallback ~/.flow_memory).

    Environment variables:
      - FLOW_MEMORY_STATE_DIR: override the state directory
      - EDUFLOW_STATE_DIR: backward-compat fallback for EduFlow users
    """

    def __init__(self, state_dir: Path | None = None) -> None:
        if state_dir is not None:
            self._state_dir = Path(state_dir)
        else:
            env = os.environ.get("FLOW_MEMORY_STATE_DIR") or os.environ.get(
                "EDUFLOW_STATE_DIR"
            )
            if env:
                self._state_dir = Path(env)
            else:
                self._state_dir = Path.home() / ".flow_memory"

    def memory_db_file(self) -> Path:
        override = os.environ.get("FLOW_MEMORY_DB")
        if override:
            return Path(override)
        return self._state_dir / "flow_memory.db"

    def vector_index_dir(self) -> Path:
        return self._state_dir / "vector_index"

    def audit_log_file(self) -> Path:
        return self._state_dir / "audit.log"

    def export_log_file(self) -> Path:
        return self._state_dir / "export.log"

    def obsidian_root(self) -> Path:
        env = os.environ.get("FLOW_MEMORY_OBSIDIAN_ROOT")
        if env:
            return Path(env)
        return Path.home() / "Documents" / "ObsidianVault"


# ── Module-level singleton ────────────────────────────────────────

_provider: PathProvider | None = None


def get_path_provider() -> PathProvider:
    """Return the active PathProvider. Lazy-inits DefaultPathProvider."""
    global _provider
    if _provider is None:
        _provider = DefaultPathProvider()
        _provider.ensure_state()
    return _provider


def set_path_provider(provider: PathProvider) -> None:
    """Replace the active PathProvider."""
    global _provider
    _provider = provider
    _provider.ensure_state()
