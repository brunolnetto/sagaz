"""Run every ``sagaz`` import found in the docs' Python code blocks (#539).

A documented import that fails is the first thing a newcomer hits. This
extracts ``from sagaz... import ...`` and ``import sagaz...`` statements
(multi-line ones included) from fenced ``python`` blocks in README.md and
docs/ (except docs/archive and docs/architecture: history, and ADRs or plans that may
describe proposed APIs), runs each one, and
fails listing the ones that raise.

    python scripts/check_doc_imports.py [paths...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FENCE = re.compile(r"^```(\w*)\s*$")
IMPORT = re.compile(r"^\s*(from\s+sagaz[\w.]*\s+import\s+|import\s+sagaz)")
SKIP_DIRS = {"archive", "architecture"}  # history, and ADRs/plans describing proposals
OPTIONAL = {  # extras a plain dev install may lack; their imports are skipped, not failed
    "aiokafka",
    "aio_pika",
    "fastapi",
    "flask",
    "django",
    "gradio",
    "pyiceberg",
    "fluss",
    "langgraph",
    "pydantic_ai",
}


def python_blocks(text: str) -> list[tuple[int, list[str]]]:
    """(first line number, lines) of each fenced python block."""
    blocks, current, start, in_python = [], [], 0, None
    for number, line in enumerate(text.splitlines(), 1):
        fence = FENCE.match(line.strip())
        if fence and in_python is None:
            in_python = fence.group(1).lower() in ("python", "py", "")
            current, start = [], number + 1
        elif line.strip().startswith("```") and in_python is not None:
            if in_python:
                blocks.append((start, current))
            in_python = None
        elif in_python:
            current.append(line)
    return blocks


def imports_in(lines: list[str]) -> list[tuple[int, str]]:
    """(line offset, statement) of each sagaz import, joining parenthesized ones."""
    found, i = [], 0
    while i < len(lines):
        if IMPORT.match(lines[i]):
            statement, j = lines[i].strip(), i
            while "(" in statement and ")" not in statement and j + 1 < len(lines):
                j += 1
                statement += " " + lines[j].strip()
            found.append((i, re.sub(r"\s*#.*$", "", statement).rstrip("\\ ")))
            i = j
        i += 1
    return found


def documents(paths: list[str]) -> list[Path]:
    if paths:
        return [Path(p) for p in paths]
    docs = [p for p in Path("docs").rglob("*.md") if not SKIP_DIRS & set(p.parts)]
    return [Path("README.md"), *sorted(docs)]


def check(paths: list[str]) -> list[str]:
    failures = []
    for doc in documents(paths):
        for start, block in python_blocks(doc.read_text(encoding="utf-8")):
            for offset, statement in imports_in(block):
                try:
                    exec(statement, {})
                except ModuleNotFoundError as error:
                    if (error.name or "").split(".")[0] in OPTIONAL:
                        continue
                    failures.append(f"{doc}:{start + offset}: {statement}  ->  {error}")
                except Exception as error:  # ImportError, or a module failing to import
                    failures.append(
                        f"{doc}:{start + offset}: {statement}  ->  {type(error).__name__}: {error}"
                    )
    return failures


def main() -> int:
    failures = check(sys.argv[1:])
    for failure in failures:
        print(f"✗ {failure}")
    print(f"{len(failures)} failing documented import(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
