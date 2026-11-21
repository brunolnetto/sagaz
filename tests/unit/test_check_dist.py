"""scripts/check_dist.py keeps untracked files and oversized artifacts out of a release."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_dist.py"
spec = importlib.util.spec_from_file_location("check_dist", SCRIPT)
check_dist = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_dist)


@pytest.fixture
def tracked(monkeypatch):
    monkeypatch.setattr(check_dist, "tracked_files", lambda: {"sagaz/__init__.py"})


def make_wheel(dist: Path, *names: str, payload: bytes = b"x") -> None:
    dist.mkdir(exist_ok=True)
    with zipfile.ZipFile(dist / "sagaz-0-py3-none-any.whl", "w") as wheel:
        for name in names:
            wheel.writestr(name, payload)


def test_a_wheel_of_tracked_files_passes(tmp_path, tracked):
    make_wheel(tmp_path, "sagaz/__init__.py", "sagaz-0.dist-info/METADATA")
    assert check_dist.check(tmp_path) == []


def test_an_untracked_file_fails(tmp_path, tracked):
    make_wheel(tmp_path, "sagaz/__init__.py", "sagaz/deployment/lib/big.jar")
    assert check_dist.check(tmp_path) == [
        "sagaz-0-py3-none-any.whl: untracked file sagaz/deployment/lib/big.jar"
    ]


def test_an_oversized_artifact_fails(tmp_path, tracked, monkeypatch):
    monkeypatch.setattr(check_dist, "MAX_BYTES", 10)
    make_wheel(tmp_path, "sagaz/__init__.py", payload=b"x" * 100)
    assert any("MiB >" in problem for problem in check_dist.check(tmp_path))


def test_an_empty_dist_fails(tmp_path):
    assert check_dist.check(tmp_path) == [f"no wheel or sdist in {tmp_path}"]
