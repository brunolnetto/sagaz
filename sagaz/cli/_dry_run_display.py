"""Rich and plain-text rendering of dry-run validation and simulation results.

``console`` and ``RICH_AVAILABLE`` are re-exported by ``sagaz.cli.dry_run``.
"""

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    RICH_AVAILABLE = True
except ImportError:
    console = None  # type: ignore[assignment]
    RICH_AVAILABLE = False


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
    console.print(f"\n[bold cyan]saga_class: {saga_name}[/bold cyan]")

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
    console.print(f"\n[bold cyan]═══ saga_class: {saga_name} ═══[/bold cyan]")

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
