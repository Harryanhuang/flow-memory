"""Pre-release sanity check: ensure no leftover eduflow imports."""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path


def check_file(path: Path) -> list[str]:
    """Return list of problems found in this Python file."""
    problems: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        problems.append(f"{path}: syntax error: {e}")
        return problems

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("eduflow"):
                    problems.append(
                        f"{path}:{node.lineno}: imports eduflow: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("eduflow"):
                problems.append(
                    f"{path}:{node.lineno}: imports from eduflow: {node.module}"
                )
    return problems


def main() -> int:
    root = Path(__file__).parent.parent / "src" / "flow_memory"
    if not root.exists():
        print(f"❌ Source directory not found: {root}")
        return 1

    all_problems: list[str] = []
    for py_file in root.rglob("*.py"):
        all_problems.extend(check_file(py_file))

    if all_problems:
        print(f"❌ Found {len(all_problems)} eduflow imports in flow_memory:")
        for p in all_problems:
            print(f"   {p}")
        return 1

    print(f"✅ Clean: no eduflow imports in flow_memory source ({root})")
    return 0


if __name__ == "__main__":
    sys.exit(main())