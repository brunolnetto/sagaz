"""scripts/check_suppressions.py: a suppression comment says what and why (#594)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_suppressions.py"
spec = importlib.util.spec_from_file_location("check_suppressions", SCRIPT)
check_suppressions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_suppressions)


def messages(source: str) -> list[str]:
    return [message.split(" needs ")[0] for _, message in check_suppressions.problems_in(source)]


@pytest.mark.parametrize(
    "line",
    [
        "x = f()  # type: ignore[attr-defined]",
        "x = f()  # type: ignore[assignment, no-redef]",
        "import os  # noqa: F401",
        "q = f'{t}'  # nosec B608 - t is a literal",
        "q = f'{t}'  # nosec B608, B310 - t is a literal",
        "if x:  # pragma: no cover - the extra is installed in tests",
        "x = 1  # an ordinary comment",
    ],
)
def test_a_specific_explained_marker_passes(line):
    assert messages(line + "\n") == []


@pytest.mark.parametrize(
    ("line", "marker"),
    [
        ("x = f()  # type: ignore", "type: ignore"),
        ("x = f()  # type:ignore", "type: ignore"),
        ("import os  # noqa", "noqa"),
        ("q = f'{t}'  # nosec", "nosec"),
        ("q = f'{t}'  # nosec B608", "nosec"),
        ("q = f'{t}'  # nosec - t is a literal", "nosec"),
        ("if x:  # pragma: no cover", "pragma: no cover"),
        ("if x:  # pragma: no cover -", "pragma: no cover"),
    ],
)
def test_a_blanket_or_unexplained_marker_fails(line, marker):
    assert messages(line + "\n") == [marker]


def test_a_marker_inside_a_string_is_not_a_comment():
    source = '"""Write # type: ignore and # nosec with care."""\ntext = "# pragma: no cover"\n'
    assert messages(source) == []


def test_problems_carry_their_line():
    source = "a = 1\nb = f()  # type: ignore\n"
    assert [line for line, _ in check_suppressions.problems_in(source)] == [2]


def test_check_walks_directories_and_main_reports(tmp_path, capsys):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "bad.py").write_text("x = f()  # type: ignore\n")
    (tmp_path / "pkg" / "good.py").write_text("x = f()  # type: ignore[misc]\n")
    assert len(check_suppressions.check([tmp_path])) == 1
    assert check_suppressions.main([str(tmp_path)]) == 1
    assert "bad.py:1" in capsys.readouterr().out
    assert check_suppressions.main([str(tmp_path / "pkg" / "good.py")]) == 0


def test_the_library_itself_passes():
    assert check_suppressions.check([ROOT / "sagaz"]) == []
