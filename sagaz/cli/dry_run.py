"""
Dry-Run CLI Commands (ADR-019)

CLI interface for saga validation and simulation analysis.
Refactored to reduce complexity and reuse project discovery (v1.6.1).
"""

import json
import sys
from pathlib import Path

import click

from sagaz.cli.dry_run_ui import (
    display_project_simulation_results_plain as _display_project_simulation_results_plain_ui,
)
from sagaz.cli.dry_run_ui import (
    display_project_validation_results_plain as _display_project_validation_results_plain_ui,
)
from sagaz.cli.dry_run_ui import (
    display_simulation_results,
    display_validation_results,
)
from sagaz.cli.project import (
    _discover_sagas,
    _discover_sagas_in_directory,
    _discover_sagas_in_paths,
    _extract_sagas_from_module,
    _try_load_sagas_from_file,
)
from sagaz.dry_run import DryRunEngine, DryRunMode

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    RICH_AVAILABLE = True
except ImportError:
    console = None  # type: ignore[assignment]
    RICH_AVAILABLE = False
    Panel = None
    Table = None


# Backwards compatibility for tests (proper functions to capture patched globals)
def _display_validation_results(results, rich_available=None):
    if rich_available is None:
        rich_available = RICH_AVAILABLE
    if rich_available:
        return _display_project_validation_results_rich(results)
    return _display_project_validation_results_plain(results)


def _display_simulation_results(results, show_parallel=False, rich_available=None):
    if rich_available is None:
        rich_available = RICH_AVAILABLE
    if rich_available:
        return _display_project_simulation_results_rich(results, show_parallel)
    return _display_project_simulation_results_plain(results, show_parallel)


def _display_project_validation_results_plain(results):
    return _display_project_validation_results_plain_ui(results, echo_func=click.echo)


def _display_project_simulation_results_plain(results, show_parallel=False):
    return _display_project_simulation_results_plain_ui(
        results, show_parallel, echo_func=click.echo
    )


def _display_project_validation_results_rich(results):
    return display_validation_results(
        results, rich_available=True, echo_func=click.echo, console=console
    )


def _display_project_simulation_results_rich(results, show_parallel=False):
    return display_simulation_results(
        results, show_parallel, rich_available=True, echo_func=click.echo, console=console
    )


def _run_validation_for_sagas(sagas, ctx):
    return _run_engine_for_sagas(sagas, ctx, DryRunMode.VALIDATE)


def _run_simulation_for_sagas(sagas, ctx):
    return _run_engine_for_sagas(sagas, ctx, DryRunMode.SIMULATE)


def _discover_project_sagas(paths=None):
    return _discover_sagas_in_paths(paths or ["sagas/"])


def _load_saga(*args, **kwargs):
    return _try_load_sagas_from_file(*args, **kwargs)


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

    # Use aliases for test patching
    results = _run_validation_for_sagas(sagas, ctx)
    _display_validation_results(results)

    all_success = all(r[1].success for r in results)
    sys.exit(0 if all_success else 1)


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

    # Use aliases for test patching
    results = _run_simulation_for_sagas(sagas, ctx)
    _display_simulation_results(results, show_parallel)

    all_success = all(r[1].success for r in results)
    sys.exit(0 if all_success else 1)


def _discover_and_select_sagas(
    saga_name: str | None, operation: str, interactive: bool = False
) -> list:
    """Discover sagas and optionally select interactively."""
    import yaml

    if not Path("sagaz.yaml").exists():
        paths = ["sagas/"]
    else:
        try:
            config = yaml.safe_load(Path("sagaz.yaml").read_text(encoding="utf-8"))
            paths = config.get("paths", ["sagas/"])
        except Exception:
            paths = ["sagas/"]

    # IMPORTANT: Use _discover_project_sagas so patches on it work!
    sagas = _discover_project_sagas(paths)

    if not sagas:
        click.echo("Error: No sagas found in project. Check sagaz.yaml paths.", err=True)
        click.echo("   Have you run 'sagaz init' yet?", err=True)
        sys.exit(1)

    if saga_name:
        filtered = [s for s in sagas if s["name"] == saga_name]
        if not filtered:
            click.echo(f"Error: Saga '{saga_name}' not found in project", err=True)
            sys.exit(1)
        return filtered

    if interactive:
        selected_name = _interactive_saga_selection(sagas, operation)
        if not selected_name:
            click.echo("Aborted.")
            sys.exit(0)
        return [s for s in sagas if s["name"] == selected_name]

    return sagas


def _run_engine_for_sagas(sagas: list, ctx: dict, mode: DryRunMode) -> list:
    """Run dry-run engine for given sagas."""
    import asyncio

    engine = DryRunEngine()
    results = []
    for saga_info in sagas:
        saga_instance = saga_info["class"]()
        result = asyncio.run(engine.run(saga_instance, ctx, mode))
        results.append((saga_info["name"], result))
    return results


def _interactive_saga_selection(sagas: list[dict], operation: str) -> str | None:
    """Present interactive saga selection menu."""
    if not sagas:
        return None

    if len(sagas) == 1:
        saga_name = sagas[0]["name"]
        if RICH_AVAILABLE and console:
            console.print(f"[dim]Auto-selecting only saga: {saga_name}[/dim]")
        else:
            click.echo(f"Auto-selecting only saga: {saga_name}")
        return saga_name

    click.echo(f"\nSelect saga to {operation}:")
    for idx, saga in enumerate(sagas, 1):
        file_path = saga.get("file", "")
        click.echo(f"  {idx}. {saga['name']:<30} ({file_path})")
    click.echo("  0. Cancel")

    choice = click.prompt("Choice", type=click.IntRange(0, len(sagas)), default=1)
    return sagas[choice - 1]["name"] if choice > 0 else None
