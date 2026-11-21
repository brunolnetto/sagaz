"""Hold the library's typing debt to a budget that can only go down (#595).

``pyproject.toml`` records, under ``[tool.sagaz.typing-budget]``, how many findings each
measure has today. This script counts them again and fails when a count differs:

- above its budget, new debt was added: fix it;
- below its budget, debt was paid: lower the number in ``pyproject.toml``, so the gain
  is kept.

The measures:

- ruff rules that are not enabled yet (``ANN401`` for a bare ``Any``, ``ANN001`` for a
  parameter without a type, and so on), counted over ``sagaz/`` without the examples;
- ``type-ignore``: the ``# type: ignore`` comments in the same files.

    python scripts/check_typing_budget.py
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tokenize
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "sagaz"
EXCLUDE = "sagaz/examples"
TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore")


def budget(pyproject: Path) -> dict[str, int]:
    """The recorded budget: ``{measure: count}``."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    table = data.get("tool", {}).get("sagaz", {}).get("typing-budget", {})
    return {str(name): int(count) for name, count in table.items()}


def ruff_counts(rules: list[str], root: Path) -> Counter[str]:
    """How many findings each of *rules* has in the package."""
    if not rules:
        return Counter()
    command = [sys.executable, "-m", "ruff", "check", PACKAGE, "--exclude", EXCLUDE]
    command += ["--select", ",".join(rules), "--output-format", "json", "--no-cache"]
    done = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    return Counter(finding["code"] for finding in json.loads(done.stdout or "[]"))


def type_ignores(root: Path) -> int:
    """How many ``# type: ignore`` comments the package has."""
    total = 0
    for file in sorted((root / PACKAGE).rglob("*.py")):
        if (root / EXCLUDE) in file.parents:
            continue
        source = io.StringIO(file.read_text(encoding="utf-8"))
        total += sum(
            1
            for token in tokenize.generate_tokens(source.readline)
            if token.type == tokenize.COMMENT and TYPE_IGNORE.search(token.string)
        )
    return total


def measure(names: list[str], root: Path) -> dict[str, int]:
    """Today's count for each measure in *names*."""
    rules = [name for name in names if name != "type-ignore"]
    counts = ruff_counts(rules, root)
    found = {rule: counts.get(rule, 0) for rule in rules}
    if "type-ignore" in names:
        found["type-ignore"] = type_ignores(root)
    return found


def compare(recorded: dict[str, int], found: dict[str, int]) -> list[str]:
    """One message per measure whose count is not its budget."""
    messages = []
    for name, allowed in sorted(recorded.items()):
        count = found[name]
        if count > allowed:
            messages.append(f"{name}: {count} found, budget {allowed}: {count - allowed} added")
        elif count < allowed:
            messages.append(
                f"{name}: {count} found, budget {allowed}: "
                f"lower it to {count} in pyproject.toml ([tool.sagaz.typing-budget])"
            )
    return messages


def main(root: Path = ROOT) -> int:
    recorded = budget(root / "pyproject.toml")
    if not recorded:
        print("No [tool.sagaz.typing-budget] in pyproject.toml.")
        return 1
    messages = compare(recorded, measure(list(recorded), root))
    for message in messages:
        print(message)
    if messages:
        return 1
    print(
        "✓ typing debt is exactly on budget: " + ", ".join(f"{k}={v}" for k, v in recorded.items())
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
