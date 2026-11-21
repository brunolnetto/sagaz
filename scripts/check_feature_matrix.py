"""Check that every test the feature matrix cites still exists.

docs/reference/feature-matrix.md backs each ✅/⚠️ cell with a test id such as
``tests/unit/core/test_x.py::TestY::test_z`` (or just a file). This fails when
a cited file, class or test function is gone, so the matrix cannot silently
claim a capability whose test was deleted.

    python scripts/check_feature_matrix.py [docs/reference/feature-matrix.md]
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

CITATION = re.compile(r"`(tests/[\w/.-]+\.py)((?:::\w+)*)`")


def defined_names(path: Path) -> dict[str, set[str]]:
    """{"": module-level test functions and classes, ClassName: its methods}."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: dict[str, set[str]] = {"": set()}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names[""].add(node.name)
        if isinstance(node, ast.ClassDef):
            names[node.name] = {
                item.name
                for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            }
    return names


def check(matrix: Path) -> list[str]:
    problems = []
    cache: dict[Path, dict[str, set[str]]] = {}
    for file, parts in sorted(set(CITATION.findall(matrix.read_text(encoding="utf-8")))):
        path = Path(file)
        if not path.exists():
            problems.append(f"{file}: no such file")
            continue
        names = cache.setdefault(path, defined_names(path))
        chain = [p for p in parts.split("::") if p]
        if len(chain) == 1 and chain[0] not in names[""]:
            problems.append(f"{file}::{chain[0]}: not defined")
        elif len(chain) == 2 and chain[1] not in names.get(chain[0], set()):
            problems.append(f"{file}::{chain[0]}::{chain[1]}: not defined")
    return problems


def main() -> int:
    matrix = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/reference/feature-matrix.md")
    problems = check(matrix)
    for problem in problems:
        print(f"✗ {problem}")
    count = len(set(CITATION.findall(matrix.read_text(encoding="utf-8"))))
    print(f"{count} cited tests, {len(problems)} missing")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
