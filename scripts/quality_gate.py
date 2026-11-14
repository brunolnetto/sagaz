#!/usr/bin/env python3
"""Structural quality gate for the ``sagaz`` package.

Checks every module under the package root against three limits, configured in
``[tool.sagaz.quality-gate]`` of ``pyproject.toml``:

* cyclomatic complexity per function/method (``max-cc``),
* physical lines per module (``max-lines``),
* maintainability index per module (``min-mi``), as computed by radon.

Existing violations can be frozen in a baseline file so CI fails only on *new*
violations or on baselined ones that get *worse*; ``--strict-baseline`` also
fails on stale entries so fixed modules must be removed from the baseline.

Usage::

    python scripts/quality_gate.py                    # check (exit 1 on failure)
    python scripts/quality_gate.py --update-baseline  # record current violations
    python scripts/quality_gate.py --strict-baseline  # also reject stale entries
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from radon.complexity import cc_visit
from radon.metrics import mi_visit

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {"root": "sagaz", "max-cc": 10, "max-lines": 400, "min-mi": 20.0, "baseline": ""}


@dataclass(frozen=True)
class Violation:
    kind: str  # "cc" | "lines" | "mi"
    target: str  # module path, or "path::function" for cc
    value: float
    limit: float

    def worse_than(self, recorded: float) -> bool:
        return self.value < recorded if self.kind == "mi" else self.value > recorded

    def __str__(self) -> str:
        if self.kind == "mi":
            return f"MI {self.value:.1f} < {self.limit:g}   {self.target}"
        label = "CC" if self.kind == "cc" else "lines"
        return f"{label} {self.value:g} > {self.limit:g}   {self.target}"


def load_config(pyproject: Path) -> dict:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    section = data.get("tool", {}).get("sagaz", {}).get("quality-gate", {})
    return {**DEFAULTS, **section}


def scan(root: Path, config: dict) -> list[Violation]:
    violations: list[Violation] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        lines = len(source.splitlines())
        if lines > config["max-lines"]:
            violations.append(Violation("lines", rel, lines, config["max-lines"]))
        if source.strip():
            mi = round(mi_visit(source, multi=True), 2)
            if mi < config["min-mi"]:
                violations.append(Violation("mi", rel, mi, config["min-mi"]))
        for block in cc_visit(source):
            if block.complexity > config["max-cc"]:
                name = f"{rel}::{block.fullname}"
                violations.append(Violation("cc", name, block.complexity, config["max-cc"]))
    return violations


def to_baseline(violations: list[Violation]) -> dict[str, dict[str, float]]:
    baseline: dict[str, dict[str, float]] = {"cc": {}, "lines": {}, "mi": {}}
    for violation in violations:
        baseline[violation.kind][violation.target] = violation.value
    return baseline


def evaluate(
    violations: list[Violation], baseline: dict[str, dict[str, float]], *, strict: bool
) -> tuple[list[str], list[str]]:
    """Return (failures, notes) for violations judged against the baseline."""
    failures: list[str] = []
    current: set[tuple[str, str]] = set()
    for violation in violations:
        current.add((violation.kind, violation.target))
        recorded = baseline.get(violation.kind, {}).get(violation.target)
        if recorded is None:
            failures.append(f"new        {violation}")
        elif violation.worse_than(recorded):
            failures.append(f"worse      {violation}  (baseline {recorded:g})")
    stale = [
        f"stale      {kind} {target}"
        for kind, entries in baseline.items()
        for target in entries
        if (kind, target) not in current
    ]
    if strict:
        failures.extend(stale)
        return failures, []
    return failures, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--strict-baseline", action="store_true")
    parser.add_argument("--pyproject", type=Path, default=REPO_ROOT / "pyproject.toml")
    args = parser.parse_args(argv)

    config = load_config(args.pyproject)
    violations = scan(REPO_ROOT / config["root"], config)
    baseline_path = REPO_ROOT / config["baseline"] if config["baseline"] else None

    if args.update_baseline:
        if baseline_path is None:
            print("No baseline configured in [tool.sagaz.quality-gate].", file=sys.stderr)
            return 2
        baseline_path.write_text(
            json.dumps(to_baseline(violations), indent=2, sort_keys=True) + "\n"
        )
        print(f"Baseline updated: {len(violations)} violation(s) in {baseline_path.name}")
        return 0

    baseline = (
        json.loads(baseline_path.read_text())
        if baseline_path is not None and baseline_path.exists()
        else {}
    )
    failures, notes = evaluate(violations, baseline, strict=args.strict_baseline)

    limits = f"CC <= {config['max-cc']}, lines <= {config['max-lines']}, MI >= {config['min-mi']}"
    print(
        f"Quality gate ({limits}): {len(violations)} violation(s), "
        f"{sum(len(v) for v in baseline.values())} baselined"
    )
    for line in notes:
        print(f"  note: {line}  -> remove it with --update-baseline")
    if failures:
        print("FAILED:")
        for line in failures:
            print(f"  {line}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
