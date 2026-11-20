"""Fail when a relative link in the docs points to a file that does not exist.

Checks README.md and docs/ (except docs/archive, kept as written). Links inside
fenced code blocks and external URLs are ignored.

    python scripts/check_doc_links.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
FENCE = re.compile(r"```.*?```", re.S)


def broken_links(root: Path) -> list[str]:
    docs = [p for p in (root / "docs").rglob("*.md") if "archive" not in p.parts]
    broken = []
    for md in [root / "README.md", *docs]:
        text = FENCE.sub("", md.read_text(encoding="utf-8", errors="ignore"))
        for link in LINK.findall(text):
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            if not (md.parent / link).resolve().exists():
                broken.append(f"{md.relative_to(root)}: {link}")
    return broken


def main() -> int:
    broken = broken_links(Path(__file__).resolve().parents[1])
    for line in broken:
        print(line)
    print(f"{len(broken)} broken link(s)", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
