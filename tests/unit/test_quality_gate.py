"""Tests for scripts/quality_gate.py (structural quality gate)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "quality_gate.py"
spec = importlib.util.spec_from_file_location("quality_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
sys.modules["quality_gate"] = gate  # dataclasses resolve their module here
spec.loader.exec_module(gate)

BRANCHY = "def f(x):\n" + "".join(f"    if x == {i}:\n        return {i}\n" for i in range(12))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A fake repository with a package and a pyproject using small limits."""
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "ok.py").write_text("def g():\n    return 1\n")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.sagaz.quality-gate]\n"
        'root = "pkg"\nmax-cc = 10\nmax-lines = 30\nmin-mi = 20\n'
        'baseline = "baseline.json"\n'
    )
    return tmp_path


def _run(repo, *args):
    return gate.main([*args, "--pyproject", str(repo / "pyproject.toml")])


def test_clean_package_passes(repo, capsys):
    assert _run(repo) == 0
    assert "0 violation(s)" in capsys.readouterr().out


def test_each_limit_is_enforced(repo, capsys):
    (repo / "pkg" / "branchy.py").write_text(BRANCHY)
    (repo / "pkg" / "long.py").write_text("x = 1\n" * 31)

    assert _run(repo) == 1
    out = capsys.readouterr().out
    assert "new        CC 13 > 10   pkg/branchy.py::f" in out
    assert "new        lines 31 > 30   pkg/long.py" in out


def test_low_maintainability_is_reported():
    violations = [gate.Violation("mi", "pkg/x.py", 12.5, 20)]
    failures, _ = gate.evaluate(violations, {}, strict=False)
    assert failures == ["new        MI 12.5 < 20   pkg/x.py"]


def test_baselined_violation_passes_until_it_gets_worse(repo, capsys):
    long_module = repo / "pkg" / "long.py"
    long_module.write_text("x = 1\n" * 31)
    assert _run(repo, "--update-baseline") == 0
    assert json.loads((repo / "baseline.json").read_text())["lines"] == {"pkg/long.py": 31}

    assert _run(repo) == 0
    long_module.write_text("x = 1\n" * 35)
    assert _run(repo) == 1
    assert "worse      lines 35 > 30   pkg/long.py  (baseline 31)" in capsys.readouterr().out


def test_mi_regression_counts_as_worse():
    violation = gate.Violation("mi", "pkg/x.py", 10.0, 20)
    failures, _ = gate.evaluate([violation], {"mi": {"pkg/x.py": 15.0}}, strict=False)
    assert failures == ["worse      MI 10.0 < 20   pkg/x.py  (baseline 15)"]


def test_fixed_module_is_a_note_or_a_failure_in_strict_mode(repo, capsys):
    long_module = repo / "pkg" / "long.py"
    long_module.write_text("x = 1\n" * 31)
    _run(repo, "--update-baseline")
    long_module.write_text("x = 1\n")

    assert _run(repo) == 0
    assert "note: stale      lines pkg/long.py" in capsys.readouterr().out
    assert _run(repo, "--strict-baseline") == 1
    assert "stale      lines pkg/long.py" in capsys.readouterr().out


def test_update_requires_a_configured_baseline(repo):
    (repo / "pyproject.toml").write_text('[tool.sagaz.quality-gate]\nroot = "pkg"\n')
    assert _run(repo, "--update-baseline") == 2


def test_empty_modules_are_skipped_for_mi(repo):
    (repo / "pkg" / "__init__.py").write_text("")
    assert _run(repo) == 0


def test_repository_does_not_regress_against_its_baseline():
    """The real package may only shrink its violations (no new or worse ones)."""
    assert gate.main([]) == 0
