"""scripts/check_typing_budget.py: typing debt can only go down (#595)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_typing_budget.py"
spec = importlib.util.spec_from_file_location("check_typing_budget", SCRIPT)
check_typing_budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_typing_budget)

UNTYPED = (
    "from typing import Any\n\n\ndef f(x: Any, y) -> Any:\n    return x  # type: ignore[misc]\n"
)


def project(tmp_path: Path, budget: str, source: str = UNTYPED) -> Path:
    (tmp_path / "pyproject.toml").write_text(f"[tool.sagaz.typing-budget]\n{budget}\n")
    package = tmp_path / "sagaz"
    package.mkdir()
    (package / "module.py").write_text(source)
    examples = package / "examples"
    examples.mkdir()
    (examples / "demo.py").write_text(UNTYPED)  # examples are not counted
    return tmp_path


def test_compare_is_silent_on_budget():
    assert check_typing_budget.compare({"ANN401": 3}, {"ANN401": 3}) == []


def test_compare_reports_added_debt():
    (message,) = check_typing_budget.compare({"ANN401": 3}, {"ANN401": 5})
    assert "5 found, budget 3: 2 added" in message


def test_compare_asks_to_lower_a_budget_that_was_beaten():
    (message,) = check_typing_budget.compare({"ANN401": 3}, {"ANN401": 1})
    assert "lower it to 1" in message


def test_measure_counts_ruff_rules_and_type_ignores_outside_examples(tmp_path):
    root = project(tmp_path, "ANN401 = 0")
    found = check_typing_budget.measure(["ANN401", "ANN001", "type-ignore"], root)
    assert found == {"ANN401": 2, "ANN001": 1, "type-ignore": 1}


def test_a_type_ignore_in_a_string_is_not_counted(tmp_path):
    root = project(tmp_path, "type-ignore = 0", 'TEXT = "# type: ignore"\n')
    assert check_typing_budget.type_ignores(root) == 0


def test_main_passes_on_budget_and_fails_off_it(tmp_path, capsys):
    root = project(tmp_path, 'ANN401 = 2\n"type-ignore" = 1')
    assert check_typing_budget.main(root) == 0
    assert "exactly on budget" in capsys.readouterr().out
    (root / "pyproject.toml").write_text("[tool.sagaz.typing-budget]\nANN401 = 1\n")
    assert check_typing_budget.main(root) == 1
    assert "1 added" in capsys.readouterr().out


def test_main_fails_without_a_budget(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert check_typing_budget.main(tmp_path) == 1
    assert "No [tool.sagaz.typing-budget]" in capsys.readouterr().out


def test_the_library_is_on_its_recorded_budget():
    recorded = check_typing_budget.budget(ROOT / "pyproject.toml")
    assert recorded, "pyproject.toml must record a typing budget"
    assert (
        check_typing_budget.compare(recorded, check_typing_budget.measure(list(recorded), ROOT))
        == []
    )
