"""Check that the release-facing documents agree with the project's version (#642).

Three documents say which version is released and what comes next:
``docs/reference/feature-matrix.md``, ``docs/ROADMAP.md`` and
``docs/planning/release-plan.md``. They drifted apart before: the roadmap named a release
four versions old. This fails when

- one of them names another released version than ``project.version`` in ``pyproject.toml``;
- the feature matrix's audit header lacks a date, or a full commit id as its revision;
- the roadmap and the release plan disagree on what is in development or next, or name a
  version that is not after the released one;
- the released version has no row in the roadmap's and the release plan's tables.

It checks structure and metadata only. Whether a claim of the matrix is true is a
person's review, which the audit header records.

    python scripts/check_release_docs.py [repository root]
"""

from __future__ import annotations

import re
import sys
import tomllib
from datetime import date
from pathlib import Path

VERSION = r"v(\d+\.\d+\.\d+)"
AUDIT = re.compile(
    rf"^> \*\*Audited\*\*: (\S+) \| \*\*Version\*\*: {VERSION} \| \*\*Revision\*\*: `(\w+)`",
    re.M,
)
SEQUENCE = re.compile(
    rf"^> \*\*Latest release\*\*: {VERSION}[^|]*\| \*\*In development\*\*: {VERSION}[^|]*"
    rf"\| \*\*Next\*\*: {VERSION}",
    re.M,
)


def _number(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _matrix(text: str, released: str) -> list[str]:
    found = AUDIT.search(text)
    if found is None:
        return [
            "feature-matrix.md: no audit header "
            "(> **Audited**: <date> | **Version**: v<x.y.z> | **Revision**: `<commit id>`)"
        ]
    audited, version, revision = found.groups()
    problems = []
    try:
        date.fromisoformat(audited)
    except ValueError:
        problems.append(f"feature-matrix.md: the audit date {audited!r} is not YYYY-MM-DD")
    if version != released:
        problems.append(
            f"feature-matrix.md: audited for v{version}, but pyproject.toml is at {released}: "
            "audit it again for this release"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        problems.append(
            f"feature-matrix.md: the revision {revision!r} is not a full commit id "
            "(git rev-parse HEAD)"
        )
    return problems


def _sequence(name: str, text: str, released: str) -> tuple[list[str], tuple[str, str] | None]:
    found = SEQUENCE.search(text)
    if found is None:
        return [
            f"{name}: no line '> **Latest release**: v… | **In development**: v… | **Next**: v…'"
        ], None
    latest, developing, following = found.groups()
    problems = []
    if latest != released:
        problems.append(
            f"{name}: the latest release is v{latest}, but pyproject.toml is at {released}"
        )
    if not _number(latest) < _number(developing) < _number(following):
        problems.append(f"{name}: v{latest}, v{developing}, v{following} are not in release order")
    if not re.search(rf"^\| v{re.escape(released)}\s*\|.*", text, re.M):
        problems.append(f"{name}: no table row for the released v{released}")
    return problems, (developing, following)


def check(root: Path) -> list[str]:
    with (root / "pyproject.toml").open("rb") as file:
        released = tomllib.load(file)["project"]["version"]
    docs = root / "docs"
    problems = _matrix((docs / "reference/feature-matrix.md").read_text("utf-8"), released)
    plans = []
    for name in ("ROADMAP.md", "planning/release-plan.md"):
        found, plan = _sequence(name, (docs / name).read_text("utf-8"), released)
        problems += found
        plans.append(plan)
    if None not in plans and plans[0] != plans[1]:
        problems.append(
            f"ROADMAP.md plans {plans[0]} and release-plan.md plans {plans[1]}: "
            "they must name the same versions in development and next"
        )
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    problems = check(root)
    for problem in problems:
        print(f"✗ {problem}")
    if not problems:
        print("✓ the feature matrix, the roadmap and the release plan agree with pyproject.toml")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
