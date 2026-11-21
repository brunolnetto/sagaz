"""scripts/check_feature_matrix.py keeps the matrix's cited tests real."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_feature_matrix.py"
spec = importlib.util.spec_from_file_location("check_feature_matrix", SCRIPT)
check_feature_matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_feature_matrix)


def test_the_repository_matrix_cites_only_existing_tests():
    assert check_feature_matrix.check(Path("docs/reference/feature-matrix.md")) == []


def test_missing_files_classes_and_functions_are_reported(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_top():\n    pass\n\nclass TestK:\n    async def test_m(self):\n        pass\n"
    )
    matrix = tmp_path / "m.md"
    matrix.write_text(
        "`tests/test_a.py::test_top` `tests/test_a.py::TestK::test_m` `tests/test_a.py`\n"
        "`tests/test_a.py::test_gone` `tests/test_a.py::TestK::test_gone` `tests/nope.py`\n"
    )
    assert check_feature_matrix.check(matrix) == [
        "tests/nope.py: no such file",
        "tests/test_a.py::TestK::test_gone: not defined",
        "tests/test_a.py::test_gone: not defined",
    ]
