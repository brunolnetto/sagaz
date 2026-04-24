"""
UI and display logic for dry-run commands.
"""

import click

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    _console = Console()
    _RICH_AVAILABLE = True
except ImportError:
    _console = None
    _RICH_AVAILABLE = False
    Panel = None
    Table = None

def display_validation_results(results: list, rich_available: bool = None, echo_func=None, console=None):
    """Display validation results."""
    if rich_available is None:
        rich_available = _RICH_AVAILABLE
    
    con = console or _console
    
    if rich_available and con:
        _display_project_validation_results_rich(results, console=con)
    else:
        display_project_validation_results_plain(results, echo_func=echo_func)


def display_simulation_results(results: list, show_parallel: bool = False, rich_available: bool = None, echo_func=None, console=None):
    """Display simulation results."""
    if rich_available is None:
        rich_available = _RICH_AVAILABLE
        
    con = console or _console
        
    if rich_available and con:
        _display_project_simulation_results_rich(results, show_parallel, console=con)
    else:
        display_project_simulation_results_plain(results, show_parallel, echo_func=echo_func)


def _display_project_validation_results_rich(results, console=None):
    """Display validation results for multiple sagas with Rich formatting."""
    con = console or _console
    all_success = all(result.success for _, result in results)

    if all_success:
        con.print(Panel("[green]✓ All sagas validated successfully[/green]", title="Success"))
    else:
        con.print(Panel("[red]✗ Some sagas failed validation[/red]", title="Error"))

    for saga_name, result in results:
        _display_single_validation_result_rich(saga_name, result, console=con)


def _display_single_validation_result_rich(saga_name: str, result, console=None):
    """Display validation result for a single saga."""
    con = console or _console
    con.print(f"\n[bold cyan]Saga: {saga_name}[/bold cyan]")

    if result.success:
        if result.validation_checks:
            table = _build_validation_table(result.validation_checks)
            con.print(table)

        if result.validation_warnings:
            con.print("\n[yellow]⚠ Warnings:[/yellow]")
            for warning in result.validation_warnings:
                con.print(f"  • {warning}")
    else:
        con.print("[red]Errors:[/red]")
        for error in result.validation_errors:
            con.print(f"  • {error}")

        if result.validation_warnings:
            con.print("\n[yellow]⚠ Warnings:[/yellow]")
            for warning in result.validation_warnings:
                con.print(f"  • {warning}")


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


def display_project_validation_results_plain(results, echo_func=None):
    """Fallback plain text display."""
    echo = echo_func or print
    for saga_name, result in results:
        status = "PASSED" if result.success else "FAILED"
        echo(f"Saga {saga_name}: {status}")
        if not result.success:
            for error in result.validation_errors:
                echo(f"  - {error}")


def _display_project_simulation_results_rich(results, show_parallel: bool, console=None):
    """Display simulation results for multiple sagas with Rich formatting."""
    con = console or _console
    all_success = all(result.success for _, result in results)

    if all_success:
        con.print(Panel("[green]✓ All sagas simulated successfully[/green]", title="Success"))
    else:
        con.print(Panel("[yellow]⚠ Some sagas had issues[/yellow]", title="Warning"))

    for saga_name, result in results:
        _display_single_simulation_result_rich(saga_name, result, show_parallel, console=con)


def _display_single_simulation_result_rich(saga_name: str, result, show_parallel: bool, console=None):
    """Display simulation result for a single saga."""
    con = console or _console
    con.print(f"\n[bold cyan]═══ Saga: {saga_name} ═══[/bold cyan]")

    if not result.success:
        con.print("[red]Validation failed - cannot simulate[/red]")
        for error in result.validation_errors:
            con.print(f"  • {error}")
        return

    _display_forward_layers(result.forward_layers, console=con)

    con.print("\n[bold]Parallelization Analysis:[/bold]")
    table = _build_parallelization_table(result)
    con.print(table)

    if result.critical_path:
        con.print("\n[bold]Critical Path (Longest Chain):[/bold]")
        con.print(" → ".join(result.critical_path))

    if result.backward_layers:
        con.print("\n[bold]Compensation Layers (Rollback Order):[/bold]")
        for layer in result.backward_layers:
            con.print(f"\n[yellow]Layer {layer.layer_number}:[/yellow]")
            for step in layer.steps:
                con.print(f"  • {step}")


def _display_forward_layers(layers: list, console=None):
    """Display forward execution layers."""
    con = console or _console
    con.print("\n[bold]Forward Execution Layers (Parallelizable Groups):[/bold]")
    for layer in layers:
        con.print(f"\n[yellow]Layer {layer.layer_number}:[/yellow]")
        for step in layer.steps:
            con.print(f"  • {step}")
        if layer.dependencies:
            con.print(f"  [dim]Depends on: {', '.join(sorted(layer.dependencies))}[/dim]")


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


def display_project_simulation_results_plain(results, show_parallel: bool, echo_func=None):
    """Fallback plain text display for simulation."""
    echo = echo_func or print
    for saga_name, result in results:
        echo(f"Saga {saga_name} Simulation:")
        if result.success:
            echo(f"  Steps: {', '.join(result.steps_planned)}")
            if hasattr(result, 'execution_order'):
                echo(f"  Execution Order: {' -> '.join(result.execution_order)}")
        else:
            echo("  Simulation failed validation.")
