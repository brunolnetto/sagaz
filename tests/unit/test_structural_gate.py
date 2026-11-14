"""The package must stay within the structural gate configured in pyproject.toml.

Runs the same `codebase-stats` check as CI (`[tool.codebase-stats.gates]`: CC <= 10,
<= 400 lines and maintainability index >= 20 per module), so a local `pytest`
catches a violation before it reaches review.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("codebase_stats")

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_GATE = "import sys; from codebase_stats.cli import main; sys.exit(main())"


def _gate(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", RUN_GATE, "--root", str(root), "--format", "summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


# Scanning the whole package takes ~30s on its own; under a parallel suite on a
# loaded machine it can exceed the suite-wide --timeout=60, which made this
# test fail intermittently with no gate violation.
@pytest.mark.timeout(600)
def test_package_is_within_the_structural_gate():
    result = _gate(REPO_ROOT / "sagaz")
    assert result.returncode == 0, result.stderr
    assert "gates passed" in result.stdout + result.stderr


def test_gate_rejects_an_oversized_module(tmp_path):
    """Guards the configuration itself: the limits are really enforced."""
    (tmp_path / "pyproject.toml").write_text(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "big.py").write_text("x = 1\n" * 401)

    result = _gate(package)

    assert result.returncode == 1
    assert "big.py: 401 lines > 400 (max_lines)" in result.stderr
