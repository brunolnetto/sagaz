"""
Dry-Run CLI Commands (ADR-019)

CLI interface for saga validation and simulation analysis.
"""

import json
import sys
from pathlib import Path

import click

from sagaz.dry_run import DryRunEngine, DryRunMode

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    RICH_AVAILABLE = True
except ImportError:
    console = None
    RICH_AVAILABLE = False


@click.command(name="validate")
@click.option(
    "--saga", "-s", type=str, default=None, help="Specific saga name (validates all if omitted)"
)
@click.option("--context", "-c", type=str, default="{}", help="Context JSON (default: {})")
@click.option("--interactive", "-i", is_flag=True, help="Interactive saga selection")
def validate_cmd(saga: str | None, context: str, interactive: bool):
    """Validate saga configuration for project."""
    import asyncio

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
    return sagas


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
    import asyncio

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
        return saga_name

    click.echo(f"\nSelect saga to {operation}:")
    for idx, saga in enumerate(sagas, 1):
        file_path = saga.get("file", "")
        click.echo(f"  {idx}. {saga['name']:<30} ({file_path})")
    click.echo("  0. Cancel")

    choice = click.prompt("Choice", type=click.IntRange(0, len(sagas)), default=1)

    if choice == 0:
        return None

    return sagas[choice - 1]["name"]


def _discover_project_sagas():
    """Discover sagas from project sagaz.yaml configuration."""
    from pathlib import Path

    import yaml

    if not Path("sagaz.yaml").exists():
        return []

    try:
        config = yaml.safe_load(Path("sagaz.yaml").read_text())
        paths = config.get("paths", ["sagas/"])
    except Exception:
        return []

    return _discover_sagas_in_paths(paths)


def _discover_sagas_in_paths(paths: list[str]):
    """Discover Saga classes in given paths."""
    import importlib.util
    import inspect
    import sys
    from pathlib import Path

    from sagaz import Saga

    discovered = []

    for path_str in paths:
        p = Path(path_str)
        if p.exists():
            discovered.extend(_discover_sagas_in_directory(p, sys, importlib, inspect, Saga))

    return discovered


def _discover_sagas_in_directory(directory: Path, sys, importlib, inspect, Saga):
    """Discover sagas in a specific directory."""
    discovered = []

    for file_path in directory.rglob("*.py"):
        if not file_path.name.startswith("__"):
            saga_info = _try_load_sagas_from_file(file_path, sys, importlib, inspect, Saga)
            discovered.extend(saga_info)

    return discovered


def _try_load_sagas_from_file(file_path: Path, sys, importlib, inspect, Saga):
    """Try to load sagas from a Python file."""
    try:
        module_name = f"sagaz_user_code.{file_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)

        if not (spec and spec.loader):
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        return _extract_sagas_from_module(module, file_path, inspect, Saga)
    except Exception:
        return []


def _extract_sagas_from_module(module, file_path: Path, inspect, Saga):
    """Extract Saga classes from module."""
    discovered = []

    for name, obj in inspect.getmembers(module):
        if inspect.isclass(obj) and issubclass(obj, Saga) and obj is not Saga:
            discovered.append({"name": name, "file": str(file_path), "class": obj})

    return discovered


def _load_saga(module_path: str, saga_class_name: str | None):
    """Load saga from Python module."""
    import importlib.util
    import inspect

    from sagaz import Saga

    module = _load_python_module(module_path, importlib)
    saga_cls = _find_saga_class_in_module(module, saga_class_name, inspect, Saga)

    return saga_cls()


def _load_python_module(module_path: str, importlib):
    """Load Python module from path."""
    path = Path(module_path)
    if not path.exists():
        click.echo(f"Error: Module not found: {module_path}", err=True)
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("saga_module", path)
    if spec is None or spec.loader is None:
        click.echo(f"Error: Could not load module: {module_path}", err=True)
        sys.exit(1)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def _find_saga_class_in_module(module, saga_class_name: str | None, inspect, Saga):
    """Find Saga class in module."""
    if saga_class_name:
        return _get_named_saga_class(module, saga_class_name)
    return _auto_detect_saga_class(module, inspect, Saga)


def _get_named_saga_class(module, saga_class_name: str):
    """Get specific Saga class by name."""
    saga_cls = getattr(module, saga_class_name, None)
    if saga_cls is None:
        click.echo(f"Error: Saga class '{saga_class_name}' not found", err=True)
        sys.exit(1)
    return saga_cls


def _auto_detect_saga_class(module, inspect, Saga):
    """Auto-detect Saga class in module."""
    saga_classes = [
        obj
        for name, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, Saga) and obj is not Saga
    ]

    if not saga_classes:
        click.echo("Error: No Saga class found in module", err=True)
        sys.exit(1)

    if len(saga_classes) > 1:
        click.echo(
            f"Error: Multiple Saga classes found: {[c.__name__ for c in saga_classes]}. "
            "Use --saga-class to specify.",
            err=True,
        )
        sys.exit(1)

    return saga_classes[0]


def _display_validation_result_rich(result):
    """Display validation result with Rich formatting."""
    if result.success:
        _display_validation_success_rich(result)
    else:
        _display_validation_failure_rich(result)


def _display_validation_success_rich(result):
    """Display successful validation with Rich."""
    console.print(Panel("[green]✓ Validation passed[/green]", title="Success"))

    if result.validation_checks:
        _display_validation_checks_table(result.validation_checks)

    _display_warnings_rich(result.validation_warnings)


def _display_validation_failure_rich(result):
    """Display validation failure with Rich."""
    console.print(Panel("[red]✗ Validation failed[/red]", title="Error"))
    console.print("\n[red]Errors:[/red]")
    for error in result.validation_errors:
        console.print(f"  • {error}")

    _display_warnings_rich(result.validation_warnings)


def _display_validation_checks_table(checks: dict):
    """Display validation checks in a table."""
    table = Table(title="Validation Checks", show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="green")

    table.add_row("Steps Defined", f"✓ {checks.get('step_count', 0)} steps")
    if checks.get("step_names"):
        table.add_row("Step Names", ", ".join(checks["step_names"]))
    table.add_row("Has Dependencies", "Yes" if checks.get("has_dependencies") else "No")
    table.add_row("Has Compensation", "Yes" if checks.get("has_compensation") else "No")
    table.add_row("Circular Dependencies", "None" if not checks.get("has_cycles") else "❌ Found")
    if checks.get("required_context_fields"):
        table.add_row("Required Context", ", ".join(checks["required_context_fields"]))

    console.print(table)


def _display_warnings_rich(warnings: list):
    """Display warnings with Rich formatting."""
    if warnings:
        console.print("\n[yellow]⚠ Warnings:[/yellow]")
        for warning in warnings:
            console.print(f"  • {warning}")


def _display_validation_result_plain(result):
    """Display validation result in plain text."""
    if result.success:
        if result.validation_warnings:
            for _warning in result.validation_warnings:
                pass
    else:
        for _error in result.validation_errors:
            pass

        if result.validation_warnings:
            for _warning in result.validation_warnings:
                pass


def _build_parallelization_table(result) -> Table:
    """Build parallelization analysis table."""
    table = Table(show_header=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total steps", str(len(result.steps_planned)))
    table.add_row("Sequential layers", str(result.total_layers))
    table.add_row("Max parallel width", f"{result.max_parallel_width} step(s) per layer")
    table.add_row("Parallelization ratio", f"{result.parallelization_ratio:.2f}")
    table.add_row("Critical path length", f"{len(result.critical_path)} step(s)")

    return table


def _display_forward_layers(layers: list):
    """Display forward execution layers."""
    console.print("\n[bold]Forward Execution Layers (Parallelizable Groups):[/bold]")
    for layer in layers:
        console.print(f"\n[yellow]Layer {layer.layer_number}:[/yellow]")
        for step in layer.steps:
            console.print(f"  • {step}")
        if layer.dependencies:
            console.print(f"  [dim]Depends on: {', '.join(sorted(layer.dependencies))}[/dim]")


def _display_simulation_result_rich(result, show_parallel: bool):
    """Display simulation result with Rich formatting."""
    console.print(Panel("[green]DAG Analysis Complete[/green]", title="Success"))

    _display_forward_layers(result.forward_layers)

    console.print("\n[bold cyan]Parallelization Analysis:[/bold cyan]")
    table = _build_parallelization_table(result)
    console.print(table)

    if result.critical_path:
        console.print("\n[bold cyan]Critical Path (Longest Chain):[/bold cyan]")
        console.print(" → ".join(result.critical_path))

    if result.backward_layers:
        console.print("\n[bold cyan]Compensation Layers (Rollback Order):[/bold cyan]")
        for layer in result.backward_layers:
            console.print(f"\n[yellow]Layer {layer.layer_number}:[/yellow]")
            for step in layer.steps:
                console.print(f"  • {step}")

    # Show old-style parallel groups if requested (backward compatibility)
    if show_parallel and result.parallel_groups:
        console.print("\n[dim]Legacy Parallel Groups (for reference):[/dim]")
        for idx, group in enumerate(result.parallel_groups):
            console.print(f"[dim]  Group {idx}: {', '.join(group)}[/dim]")


def _display_simulation_result_plain(result, show_parallel: bool):
    """Display simulation result in plain text."""

    for layer in result.forward_layers:
        for _step in layer.steps:
            pass
        if layer.dependencies:
            pass

    if result.critical_path:
        pass

    if result.backward_layers:
        for layer in result.backward_layers:
            for _step in layer.steps:
                pass


def _build_validation_table(checks: dict) -> Table:
    """Build validation checks table."""
    table = Table(show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="green")

    table.add_row("Steps Defined", f"✓ {checks.get('step_count', 0)} steps")
    if checks.get("step_names"):
        table.add_row("Step Names", ", ".join(checks["step_names"]))
    table.add_row("Has Dependencies", "Yes" if checks.get("has_dependencies") else "No")
    table.add_row("Has Compensation", "Yes" if checks.get("has_compensation") else "No")
    table.add_row("Circular Dependencies", "None" if not checks.get("has_cycles") else "❌ Found")
    if checks.get("required_context_fields"):
        table.add_row("Required Context", ", ".join(checks["required_context_fields"]))

    return table


def _display_single_validation_result_rich(saga_name: str, result):
    """Display validation result for a single saga."""
    console.print(f"\n[bold cyan]Saga: {saga_name}[/bold cyan]")

    if result.success:
        if result.validation_checks:
            table = _build_validation_table(result.validation_checks)
            console.print(table)

        if result.validation_warnings:
            console.print("\n[yellow]⚠ Warnings:[/yellow]")
            for warning in result.validation_warnings:
                console.print(f"  • {warning}")
    else:
        console.print("[red]Errors:[/red]")
        for error in result.validation_errors:
            console.print(f"  • {error}")

        if result.validation_warnings:
            console.print("\n[yellow]⚠ Warnings:[/yellow]")
            for warning in result.validation_warnings:
                console.print(f"  • {warning}")


def _display_project_validation_results_rich(results):
    """Display validation results for multiple sagas with Rich formatting."""
    all_success = all(result.success for _, result in results)

    if all_success:
        console.print(Panel("[green]✓ All sagas validated successfully[/green]", title="Success"))
    else:
        console.print(Panel("[red]✗ Some sagas failed validation[/red]", title="Error"))

    for saga_name, result in results:
        _display_single_validation_result_rich(saga_name, result)


def _display_project_validation_results_plain(results):
    """Display validation results for multiple sagas in plain text."""
    all_success = all(result.success for _, result in results)

    if all_success:
        pass
    else:
        pass

    for _saga_name, result in results:
        if result.success:
            if result.validation_warnings:
                for _warning in result.validation_warnings:
                    pass
        else:
            for _error in result.validation_errors:
                pass

            if result.validation_warnings:
                for _warning in result.validation_warnings:
                    pass


def _display_single_simulation_result_rich(saga_name: str, result, show_parallel: bool):
    """Display simulation result for a single saga."""
    console.print(f"\n[bold cyan]═══ Saga: {saga_name} ═══[/bold cyan]")

    if not result.success:
        console.print("[red]Validation failed - cannot simulate[/red]")
        for error in result.validation_errors:
            console.print(f"  • {error}")
        return

    _display_forward_layers(result.forward_layers)

    console.print("\n[bold]Parallelization Analysis:[/bold]")
    table = _build_parallelization_table(result)
    console.print(table)

    if result.critical_path:
        console.print("\n[bold]Critical Path (Longest Chain):[/bold]")
        console.print(" → ".join(result.critical_path))

    if result.backward_layers:
        console.print("\n[bold]Compensation Layers (Rollback Order):[/bold]")
        for layer in result.backward_layers:
            console.print(f"\n[yellow]Layer {layer.layer_number}:[/yellow]")
            for step in layer.steps:
                console.print(f"  • {step}")

    if show_parallel and result.parallel_groups:
        console.print("\n[dim]Old-style parallel groups (deprecated):[/dim]")
        for idx, group in enumerate(result.parallel_groups):
            console.print(f"[dim]  Group {idx}: {', '.join(group)}[/dim]")


def _display_project_simulation_results_rich(results, show_parallel: bool):
    """Display simulation results for multiple sagas with Rich formatting."""
    all_success = all(result.success for _, result in results)

    if all_success:
        console.print(Panel("[green]✓ All sagas simulated successfully[/green]", title="Success"))
    else:
        console.print(Panel("[yellow]⚠ Some sagas had issues[/yellow]", title="Warning"))

    for saga_name, result in results:
        _display_single_simulation_result_rich(saga_name, result, show_parallel)


def _print_forward_layers_plain(layers: list):
    """Print forward execution layers in plain text."""
    for layer in layers:
        for _step in layer.steps:
            pass
        if layer.dependencies:
            pass


def _print_parallelization_plain(result):
    """Print parallelization analysis in plain text."""


def _display_project_simulation_results_plain(results, show_parallel: bool):
    """Display simulation results for multiple sagas in plain text."""
    all_success = all(result.success for _, result in results)

    if all_success:
        pass
    else:
        pass

    for _saga_name, result in results:
        if not result.success:
            for _error in result.validation_errors:
                pass
            continue

        _print_forward_layers_plain(result.forward_layers)
        _print_parallelization_plain(result)

        if result.critical_path:
            pass

        if result.backward_layers:
            for layer in result.backward_layers:
                for _step in layer.steps:
                    pass
