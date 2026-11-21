"""Without rich, the dry-run commands still print their results (#606)."""

from __future__ import annotations

from sagaz._dry_run_types import DryRunMode, DryRunResult, ParallelLayerInfo
from sagaz.cli._dry_run_plain import (
    _display_project_simulation_results_plain,
    _display_project_validation_results_plain,
    _display_simulation_result_plain,
    _display_validation_result_plain,
)

CHECKS = {
    "step_count": 2,
    "step_names": ["reserve", "charge"],
    "has_dependencies": True,
    "has_compensation": False,
    "has_cycles": False,
    "required_context_fields": ["order_id"],
}


def valid() -> DryRunResult:
    return DryRunResult(
        mode=DryRunMode.VALIDATE,
        success=True,
        validation_checks=CHECKS,
        validation_warnings=["step 'charge' has no compensation"],
    )


def invalid() -> DryRunResult:
    return DryRunResult(
        mode=DryRunMode.VALIDATE,
        success=False,
        validation_errors=["unknown dependency 'ship'"],
        validation_warnings=["no timeout set"],
    )


def simulated() -> DryRunResult:
    return DryRunResult(
        mode=DryRunMode.SIMULATE,
        success=True,
        steps_planned=["reserve", "charge"],
        forward_layers=[
            ParallelLayerInfo(0, ["reserve"]),
            ParallelLayerInfo(1, ["charge"], {"reserve"}),
        ],
        backward_layers=[ParallelLayerInfo(0, ["reserve"])],
        total_layers=2,
        max_parallel_width=1,
        critical_path=["reserve", "charge"],
        parallelization_ratio=1.0,
        parallel_groups=[["reserve"], ["charge"]],
    )


def test_a_valid_saga_shows_its_checks_and_warnings(capsys):
    _display_validation_result_plain(valid())
    out = capsys.readouterr().out
    assert "Validation passed" in out
    assert "Steps defined: 2" in out
    assert "Step names: reserve, charge" in out
    assert "Required context: order_id" in out
    assert "step 'charge' has no compensation" in out


def test_an_invalid_saga_shows_its_errors_and_warnings(capsys):
    _display_validation_result_plain(invalid())
    out = capsys.readouterr().out
    assert "Validation failed" in out
    assert "unknown dependency 'ship'" in out
    assert "no timeout set" in out


def test_a_simulation_shows_layers_metrics_and_paths(capsys):
    _display_simulation_result_plain(simulated(), show_parallel=True)
    out = capsys.readouterr().out
    assert "Layer 0:" in out
    assert "  - reserve" in out
    assert "Depends on: reserve" in out
    assert "Total steps: 2" in out
    assert "Sequential layers: 2" in out
    assert "reserve -> charge" in out
    assert "Compensation layers" in out
    assert "Group 1: charge" in out


def test_legacy_groups_are_shown_only_on_request(capsys):
    _display_simulation_result_plain(simulated(), show_parallel=False)
    assert "Legacy parallel groups" not in capsys.readouterr().out


def test_project_validation_names_each_saga_and_its_problems(capsys):
    _display_project_validation_results_plain([("Orders", valid()), ("Shipping", invalid())])
    out = capsys.readouterr().out
    assert "Some sagas failed validation" in out
    assert "saga_class: Orders" in out
    assert "saga_class: Shipping" in out
    assert "unknown dependency 'ship'" in out


def test_project_validation_reports_success(capsys):
    _display_project_validation_results_plain([("Orders", valid())])
    assert "All sagas validated successfully" in capsys.readouterr().out


def test_project_simulation_shows_plans_and_failures(capsys):
    results = [("Orders", simulated()), ("Shipping", invalid())]
    _display_project_simulation_results_plain(results, show_parallel=False)
    out = capsys.readouterr().out
    assert "Some sagas had issues" in out
    assert "=== saga_class: Orders ===" in out
    assert "reserve -> charge" in out
    assert "Validation failed - cannot simulate" in out
    assert "unknown dependency 'ship'" in out
