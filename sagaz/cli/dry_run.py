"""
Dry-Run CLI Commands (ADR-019)

CLI interface for saga validation and simulation analysis.

Saga discovery and result rendering live in private sibling modules and are
re-exported here.
"""

import json
import sys

import click

from sagaz.cli._dry_run_discovery import (
    _auto_detect_saga_class,
    _discover_project_sagas,
    _discover_sagas_in_directory,
    _discover_sagas_in_paths,
    _extract_sagas_from_module,
    _find_saga_class_in_module,
    _get_named_saga_class,
    _load_python_module,
    _load_saga,
    _try_load_sagas_from_file,
)
from sagaz.cli._dry_run_display import (
    RICH_AVAILABLE,
    _build_parallelization_table,
    _build_validation_table,
    _display_forward_layers,
    _display_project_simulation_results_plain,
    _display_project_simulation_results_rich,
    _display_project_validation_results_plain,
    _display_project_validation_results_rich,
    _display_simulation_result_plain,
    _display_simulation_result_rich,
    _display_single_simulation_result_rich,
    _display_single_validation_result_rich,
    _display_validation_checks_table,
    _display_validation_failure_rich,
    _display_validation_result_plain,
    _display_validation_result_rich,
    _display_validation_success_rich,
    _display_warnings_rich,
    _print_forward_layers_plain,
    _print_parallelization_plain,
    console,
)
from sagaz.dry_run import DryRunEngine, DryRunMode

__all__ = [
    "RICH_AVAILABLE",
    "DryRunEngine",
    "DryRunMode",
    "_auto_detect_saga_class",
    "_build_parallelization_table",
    "_build_validation_table",
    "_discover_and_select_sagas",
    "_discover_project_sagas",
    "_discover_sagas_in_directory",
    "_discover_sagas_in_paths",
    "_display_forward_layers",
    "_display_project_simulation_results_plain",
    "_display_project_simulation_results_rich",
    "_display_project_validation_results_plain",
    "_display_project_validation_results_rich",
    "_display_simulation_result_plain",
    "_display_simulation_result_rich",
    "_display_simulation_results",
    "_display_single_simulation_result_rich",
    "_display_single_validation_result_rich",
    "_display_validation_checks_table",
    "_display_validation_failure_rich",
    "_display_validation_result_plain",
    "_display_validation_result_rich",
    "_display_validation_results",
    "_display_validation_success_rich",
    "_display_warnings_rich",
    "_extract_sagas_from_module",
    "_find_saga_class_in_module",
    "_get_named_saga_class",
    "_interactive_saga_selection",
    "_load_python_module",
    "_load_saga",
    "_print_forward_layers_plain",
    "_print_parallelization_plain",
    "_run_simulation_for_sagas",
    "_run_validation_for_sagas",
    "_try_load_sagas_from_file",
    "console",
    "simulate_cmd",
    "validate_cmd",
]


@click.command(name="validate")
@click.option(
    "--saga", "-s", type=str, default=None, help="Specific saga name (validates all if omitted)"
)
@click.option("--context", "-c", type=str, default="{}", help="Context JSON (default: {})")
@click.option("--interactive", "-i", is_flag=True, help="Interactive saga selection")
def validate_cmd(saga: str | None, context: str, interactive: bool):
    """Validate saga configuration for project."""
    ctx = json.loads(context)
    sagas = _discover_and_select_sagas(saga, "validate", interactive)
    results = _run_validation_for_sagas(sagas, ctx)
    _display_validation_results(results)

    all_success = all(r[1].success for r in results)
    sys.exit(0 if all_success else 1)


def _discover_and_select_sagas(
    saga_name: str | None, operation: str, interactive: bool = False
) -> list:
    """Discover sagas and optionally select interactively."""
    sagas = _discover_project_sagas()

    if not sagas:
        click.echo("Error: No sagas found in project. Check sagaz.yaml paths.", err=True)
        click.echo("   Have you run 'sagaz init' yet?", err=True)
        sys.exit(1)

    # If saga name specified, filter to that specific saga
    if saga_name:
        filtered_sagas = [s for s in sagas if s["name"] == saga_name]
        if not filtered_sagas:
            click.echo(f"Error: Saga '{saga_name}' not found in project", err=True)
            sys.exit(1)
        return filtered_sagas

    # If interactive flag set, prompt for selection
    if interactive:
        selected_name = _interactive_saga_selection(sagas, operation)
        if not selected_name:
            click.echo("Aborted.")
            sys.exit(0)
        return [s for s in sagas if s["name"] == selected_name]

    # Default: return all sagas
    return sagas  # type: ignore[no-any-return]


def _run_validation_for_sagas(sagas: list, ctx: dict) -> list:
    """Run validation for all sagas."""
    import asyncio

    engine = DryRunEngine()
    results = []

    for saga_info in sagas:
        saga_instance = saga_info["class"]()
        result = asyncio.run(engine.run(saga_instance, ctx, DryRunMode.VALIDATE))
        results.append((saga_info["name"], result))

    return results


def _display_validation_results(results: list):
    """Display validation results."""
    if RICH_AVAILABLE and console:
        _display_project_validation_results_rich(results)
    else:
        _display_project_validation_results_plain(results)


@click.command(name="simulate")
@click.option(
    "--saga", "-s", type=str, default=None, help="Specific saga name (simulates all if omitted)"
)
@click.option("--context", "-c", type=str, default="{}", help="Context JSON (default: {})")
@click.option("--show-parallel", "-p", is_flag=True, help="Show parallel execution groups")
@click.option("--interactive", "-i", is_flag=True, help="Interactive saga selection")
def simulate_cmd(saga: str | None, context: str, show_parallel: bool, interactive: bool):
    """Simulate saga execution and show step order."""
    ctx = json.loads(context)
    sagas = _discover_and_select_sagas(saga, "simulate", interactive)
    results = _run_simulation_for_sagas(sagas, ctx)
    _display_simulation_results(results, show_parallel)

    all_success = all(r[1].success for r in results)
    sys.exit(0 if all_success else 1)


def _run_simulation_for_sagas(sagas: list, ctx: dict) -> list:
    """Run simulation for all sagas."""
    import asyncio

    engine = DryRunEngine()
    results = []

    for saga_info in sagas:
        saga_instance = saga_info["class"]()
        result = asyncio.run(engine.run(saga_instance, ctx, DryRunMode.SIMULATE))
        results.append((saga_info["name"], result))

    return results


def _display_simulation_results(results: list, show_parallel: bool):
    """Display simulation results."""
    if RICH_AVAILABLE and console:
        _display_project_simulation_results_rich(results, show_parallel)
    else:
        _display_project_simulation_results_plain(results, show_parallel)


# =============================================================================
# Helper Functions
# =============================================================================


def _interactive_saga_selection(sagas: list[dict], operation: str) -> str | None:
    """Present interactive saga selection menu. Returns saga name or None if cancelled."""
    if not sagas:
        return None

    # If only one saga, use it automatically
    if len(sagas) == 1:
        saga_name = sagas[0]["name"]
        if RICH_AVAILABLE and console:
            console.print(f"[dim]Auto-selecting only saga: {saga_name}[/dim]")
        else:
            click.echo(f"Auto-selecting only saga: {saga_name}")
        return saga_name  # type: ignore[no-any-return]

    click.echo(f"\nSelect saga to {operation}:")
    for idx, saga in enumerate(sagas, 1):
        file_path = saga.get("file", "")
        click.echo(f"  {idx}. {saga['name']:<30} ({file_path})")
    click.echo("  0. Cancel")

    choice = click.prompt("Choice", type=click.IntRange(0, len(sagas)), default=1)

    if choice == 0:
        return None

    return sagas[choice - 1]["name"]  # type: ignore[no-any-return]
