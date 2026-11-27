"""scripts/check_release_docs.py keeps the release-facing documents in step (#642)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "check_release_docs", ROOT / "scripts" / "check_release_docs.py"
)
check_release_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_release_docs)

SHA = "0123456789abcdef0123456789abcdef01234567"


def repository(tmp_path: Path, **changes: str) -> Path:
    """A repository at 2.6.0 whose documents agree; *changes* replace a document."""
    files = {
        "pyproject.toml": '[project]\nversion = "2.6.0"\n',
        "docs/reference/feature-matrix.md": (
            f"# Matrix\n\n> **Audited**: 2026-11-27 | **Version**: v2.6.0 | **Revision**: `{SHA}`\n"
        ),
        "docs/ROADMAP.md": (
            "> **Latest release**: v2.6.0 (2026-11-26) | **In development**: v2.6.1, Fixes"
            " | **Next**: v2.7.0, Protocol\n\n| v2.6.0 | 11 | Mode parity | x |\n"
        ),
        "docs/planning/release-plan.md": (
            "> **Latest release**: v2.6.0 (2026-11-26) | **In development**: v2.6.1"
            " | **Next**: v2.7.0\n\n| v2.6.0  | 11   | Mode Parity | Released 2026-11-26 |\n"
        ),
    }
    files.update({name.replace("__", "/"): text for name, text in changes.items()})
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_the_repository_documents_agree():
    assert check_release_docs.check(ROOT) == []


def test_documents_that_agree_pass(tmp_path):
    assert check_release_docs.check(repository(tmp_path)) == []


def test_a_bumped_version_asks_for_a_new_audit_and_new_headers(tmp_path):
    root = repository(tmp_path, **{"pyproject.toml": '[project]\nversion = "2.6.1"\n'})
    problems = check_release_docs.check(root)
    assert any("audit it again" in p for p in problems)
    assert sum("pyproject.toml is at 2.6.1" in p for p in problems) == 3
    assert sum("no table row for the released v2.6.1" in p for p in problems) == 2


@pytest.mark.parametrize(
    ("header", "said"),
    [
        ("no header at all", "no audit header"),
        (f"> **Audited**: 27/11/2026 | **Version**: v2.6.0 | **Revision**: `{SHA}`", "YYYY-MM-DD"),
        (
            "> **Audited**: 2026-11-27 | **Version**: v2.6.0 | **Revision**: `develop`",
            "full commit",
        ),
        (
            "> **Audited**: 2026-11-27 | **Version**: v2.6.0 | **Revision**: `0123abc`",
            "full commit",
        ),
    ],
)
def test_the_audit_header_needs_a_date_and_a_full_commit_id(tmp_path, header, said):
    root = repository(tmp_path, **{"docs__reference__feature-matrix.md": header + "\n"})
    (problem,) = check_release_docs.check(root)
    assert said in problem


def test_the_roadmap_and_the_plan_must_plan_the_same_versions(tmp_path):
    root = repository(
        tmp_path,
        **{
            "docs__ROADMAP.md": (
                "> **Latest release**: v2.6.0 | **In development**: v2.6.1 | **Next**: v3.0.0\n"
                "| v2.6.0 | x |\n"
            )
        },
    )
    (problem,) = check_release_docs.check(root)
    assert "must name the same versions" in problem


def test_versions_out_of_order_and_a_missing_line_are_reported(tmp_path):
    root = repository(
        tmp_path,
        **{
            "docs__ROADMAP.md": (
                "> **Latest release**: v2.6.0 | **In development**: v2.5.0 | **Next**: v2.7.0\n"
                "| v2.6.0 | x |\n"
            ),
            "docs__planning__release-plan.md": "> **Current version**: 1.8.0\n",
        },
    )
    problems = check_release_docs.check(root)
    assert any("not in release order" in p for p in problems)
    assert any("release-plan.md: no line" in p for p in problems)


def test_the_command_says_what_is_wrong_and_fails(tmp_path, capsys):
    root = repository(tmp_path, **{"pyproject.toml": '[project]\nversion = "9.9.9"\n'})
    assert check_release_docs.main(["check_release_docs.py", str(root)]) == 1
    assert "✗" in capsys.readouterr().out
    assert check_release_docs.main(["check_release_docs.py", str(repository(tmp_path))]) == 0
    assert "✓" in capsys.readouterr().out
