from __future__ import annotations

import importlib
import ast
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_declared_console_entry_points_resolve() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    for target in project["scripts"].values():
        module_name, function_name = target.split(":", maxsplit=1)
        module = importlib.import_module(module_name)
        assert callable(getattr(module, function_name))


def test_package_has_no_eduflow_runtime_imports() -> None:
    offenders = []
    for source in (ROOT / "src" / "flow_memory").rglob("*.py"):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            if "eduflow" in module.split(",") or module.startswith("eduflow."):
                offenders.append(source.relative_to(ROOT).as_posix())

    assert offenders == []


def test_vector_store_preserves_legacy_public_exports() -> None:
    vector_store = importlib.import_module("flow_memory.vector_store")

    expected = {
        "DummyProvider",
        "EmbeddingProvider",
        "LanceDBBackend",
        "SiliconFlowEmbeddingProvider",
        "VectorBackend",
        "get_embedding_provider",
        "get_vector_backend",
        "reset_embedding_provider",
        "set_embedding_provider",
        "use_vector_backend",
    }

    assert expected <= set(vars(vector_store))


def test_cli_init_creates_database(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLOW_MEMORY_DB", str(tmp_path / "memory.db"))
    cli = importlib.import_module("flow_memory.cli")

    assert cli.main(["init"]) == 0
    assert (tmp_path / "memory.db").is_file()


def test_cli_add_and_search_round_trip(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FLOW_MEMORY_DB", str(tmp_path / "memory.db"))
    cli = importlib.import_module("flow_memory.cli")

    assert (
        cli.main(["items", "add", "team", "workflow_rule", "verify before release"])
        == 0
    )
    memory_id = capsys.readouterr().out.strip()
    assert memory_id.startswith("MI-")

    assert cli.main(["search", "verify before release"]) == 0
    assert memory_id in capsys.readouterr().out


def test_mcp_server_registers_documented_dashboard_tool() -> None:
    mcp_server = importlib.import_module("flow_memory.mcp_server")
    if mcp_server.mcp is None:
        import pytest

        pytest.skip("mcp optional dependency is not installed")

    assert "memory_dashboard" in mcp_server.mcp._tool_manager._tools
