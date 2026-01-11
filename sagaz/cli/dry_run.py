"""
Dry-Run CLI Commands (ADR-019)

CLI interface for saga dry-run validation, simulation, and estimation.
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


@click.group(name="dry-run")
def dry_run_cli():
    """
    Dry-run saga execution without side effects.
    
    Validate configuration, simulate execution, estimate costs, and trace execution
    without running actual step actions.
    """


@dry_run_cli.command(name="validate")
@click.argument("saga_module", type=str)
@click.option(
    "--context", "-c", type=str, default="{}", help="Context JSON (default: {})"
)
@click.option(
    "--saga-class", "-s", type=str, default=None, help="Saga class name (auto-detect if omitted)"
)
def validate(saga_module: str, context: str, saga_class: str | None):
    """
    Validate saga configuration.
    
    \b
    Examples:
        sagaz dry-run validate examples/order_saga.py
        sagaz dry-run validate order_saga.py --context='{"order_id": "123"}'
        sagaz dry-run validate order_saga.py --saga-class=OrderSaga
    """
    import asyncio

    # Load saga
    saga = _load_saga(saga_module, saga_class)
    ctx = json.loads(context)

    # Run validation
    engine = DryRunEngine()
    result = asyncio.run(engine.run(saga, ctx, DryRunMode.VALIDATE))

    # Display results
    if RICH_AVAILABLE and console:
        _display_validation_result_rich(result)
    else:
        _display_validation_result_plain(result)

    sys.exit(0 if result.success else 1)


@dry_run_cli.command(name="simulate")
@click.argument("saga_module", type=str)
@click.option(
    "--context", "-c", type=str, default="{}", help="Context JSON (default: {})"
)
@click.option(
    "--saga-class", "-s", type=str, default=None, help="Saga class name"
)
@click.option(
    "--show-parallel", "-p", is_flag=True, help="Show parallel execution groups"
)
def simulate(saga_module: str, context: str, saga_class: str | None, show_parallel: bool):
    """
    Simulate saga execution and show step order.
    
    \b
    Examples:
        sagaz dry-run simulate order_saga.py
        sagaz dry-run simulate order_saga.py --show-parallel
    """
    import asyncio

    saga = _load_saga(saga_module, saga_class)
    ctx = json.loads(context)

    engine = DryRunEngine()
    result = asyncio.run(engine.run(saga, ctx, DryRunMode.SIMULATE))

    if not result.success:
        _display_validation_result_plain(result)
        sys.exit(1)

    # Display simulation results
    if RICH_AVAILABLE and console:
        _display_simulation_result_rich(result, show_parallel)
    else:
        _display_simulation_result_plain(result, show_parallel)


@dry_run_cli.command(name="estimate")
@click.argument("saga_module", type=str)
@click.option(
    "--context", "-c", type=str, default="{}", help="Context JSON (default: {})"
)
@click.option(
    "--saga-class", "-s", type=str, default=None, help="Saga class name"
)
@click.option(
    "--pricing",
    "-p",
    type=str,
    multiple=True,
    help="API pricing (format: api_name=price_per_call, e.g., payment_api=0.001)",
)
@click.option(
    "--scale",
    type=int,
    default=1,
    help="Scale factor for estimation (e.g., 10000 for 10K runs)",
)
def estimate(
    saga_module: str,
    context: str,
    saga_class: str | None,
    pricing: tuple[str, ...],
    scale: int,
):
    """
    Estimate resource usage and costs.
    
    \b
    Examples:
        sagaz dry-run estimate order_saga.py
        sagaz dry-run estimate order_saga.py --pricing=payment_api=0.001
        sagaz dry-run estimate order_saga.py --scale=10000
    """
    import asyncio

    saga = _load_saga(saga_module, saga_class)
    ctx = json.loads(context)

    # Configure API pricing
    engine = DryRunEngine()
    for price_spec in pricing:
        api, price = price_spec.split("=")
        engine.set_api_pricing(api, float(price))

    result = asyncio.run(engine.run(saga, ctx, DryRunMode.ESTIMATE))

    if not result.success:
        _display_validation_result_plain(result)
        sys.exit(1)

    # Display estimates
    if RICH_AVAILABLE and console:
        _display_estimate_result_rich(result, scale)
    else:
        _display_estimate_result_plain(result, scale)


@dry_run_cli.command(name="trace")
@click.argument("saga_module", type=str)
@click.option(
    "--context", "-c", type=str, default="{}", help="Context JSON (default: {})"
)
@click.option(
    "--saga-class", "-s", type=str, default=None, help="Saga class name"
)
@click.option(
    "--show-context", is_flag=True, help="Show context changes"
)
def trace(saga_module: str, context: str, saga_class: str | None, show_context: bool):
    """
    Generate detailed execution trace.
    
    \b
    Examples:
        sagaz dry-run trace order_saga.py
        sagaz dry-run trace order_saga.py --show-context
    """
    import asyncio

    saga = _load_saga(saga_module, saga_class)
    ctx = json.loads(context)

    engine = DryRunEngine()
    result = asyncio.run(engine.run(saga, ctx, DryRunMode.TRACE))

    if not result.success:
        _display_validation_result_plain(result)
        sys.exit(1)

    # Display trace
    if RICH_AVAILABLE and console:
        _display_trace_result_rich(result, show_context)
    else:
        _display_trace_result_plain(result, show_context)


# =============================================================================
# Helper Functions
# =============================================================================


def _load_saga(module_path: str, saga_class_name: str | None):
    """Load saga from Python module."""
    import importlib.util
    import inspect

    from sagaz import Saga

    # Load module
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

    # Find saga class
    if saga_class_name:
        saga_cls = getattr(module, saga_class_name, None)
        if saga_cls is None:
            click.echo(f"Error: Saga class '{saga_class_name}' not found", err=True)
            sys.exit(1)
    else:
        # Auto-detect: find first Saga subclass
        saga_classes = []
        
        # Look for Saga subclasses
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Saga) and obj is not Saga:
                saga_classes.append(obj)

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

        saga_cls = saga_classes[0]

    # Instantiate saga
    saga = saga_cls()
    
    return saga


def _display_validation_result_rich(result):
    """Display validation result with Rich formatting."""
    if result.success:
        console.print(Panel("[green]✓ Validation passed[/green]", title="Success"))
        
        # Show what was validated
        if result.validation_checks:
            table = Table(title="Validation Checks", show_header=True)
            table.add_column("Check", style="cyan")
            table.add_column("Result", style="green")
            
            checks = result.validation_checks
            table.add_row("Steps Defined", f"✓ {checks.get('step_count', 0)} steps")
            if checks.get('step_names'):
                table.add_row("Step Names", ", ".join(checks['step_names']))
            table.add_row("Has Dependencies", "Yes" if checks.get('has_dependencies') else "No")
            table.add_row("Has Compensation", "Yes" if checks.get('has_compensation') else "No")
            table.add_row("Circular Dependencies", "None" if not checks.get('has_cycles') else "❌ Found")
            if checks.get('required_context_fields'):
                table.add_row("Required Context", ", ".join(checks['required_context_fields']))
            
            console.print(table)
        
        if result.validation_warnings:
            console.print("\n[yellow]⚠ Warnings:[/yellow]")
            for warning in result.validation_warnings:
                console.print(f"  • {warning}")
    else:
        console.print(Panel("[red]✗ Validation failed[/red]", title="Error"))
        console.print("\n[red]Errors:[/red]")
        for error in result.validation_errors:
            console.print(f"  • {error}")

        if result.validation_warnings:
            console.print("\n[yellow]⚠ Warnings:[/yellow]")
            for warning in result.validation_warnings:
                console.print(f"  • {warning}")


def _display_validation_result_plain(result):
    """Display validation result in plain text."""
    if result.success:
        print("✓ Validation passed")
        if result.validation_warnings:
            print("\nWarnings:")
            for warning in result.validation_warnings:
                print(f"  • {warning}")
    else:
        print("✗ Validation failed")
        print("\nErrors:")
        for error in result.validation_errors:
            print(f"  • {error}")

        if result.validation_warnings:
            print("\nWarnings:")
            for warning in result.validation_warnings:
                print(f"  • {warning}")


def _display_simulation_result_rich(result, show_parallel: bool):
    """Display simulation result with Rich formatting."""
    console.print(Panel("[green]Simulation Complete[/green]", title="Success"))

    table = Table(title="Execution Plan")
    table.add_column("Order", style="cyan")
    table.add_column("Step", style="green")

    for idx, step in enumerate(result.execution_order, 1):
        table.add_row(str(idx), step)

    console.print(table)
    
    # Show duration estimate if available
    if result.max_parallel_duration_ms > 0:
        duration_sec = result.max_parallel_duration_ms / 1000
        console.print(f"\n[bold]Estimated Duration (with parallelism):[/bold] {duration_sec:.2f}s")

    if show_parallel and result.parallel_groups:
        console.print("\n[bold]Parallel Execution Groups:[/bold]")
        for idx, group in enumerate(result.parallel_groups, 1):
            console.print(f"  Group {idx}: {', '.join(group)}")


def _display_simulation_result_plain(result, show_parallel: bool):
    """Display simulation result in plain text."""
    print("Simulation Complete")
    print("\nExecution Order:")
    for idx, step in enumerate(result.execution_order, 1):
        print(f"  {idx}. {step}")

    if show_parallel and result.parallel_groups:
        print("\nParallel Execution Groups:")
        for idx, group in enumerate(result.parallel_groups, 1):
            print(f"  Group {idx}: {', '.join(group)}")


def _display_estimate_result_rich(result, scale: int):
    """Display estimate result with Rich formatting."""
    console.print(Panel("[green]Estimation Complete[/green]", title="Success"))

    table = Table(title="Resource Estimates")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_column(f"Scaled (x{scale})", style="yellow")

    # Duration (sequential)
    duration_s = result.estimated_duration_ms / 1000
    scaled_duration_s = duration_s * scale
    table.add_row(
        "Duration (sequential)",
        f"{duration_s:.2f}s",
        f"{scaled_duration_s:.2f}s ({scaled_duration_s/60:.1f}m)",
    )
    
    # Duration (with parallelism) - upper bound
    if result.estimated_duration_parallel_ms > 0:
        parallel_s = result.estimated_duration_parallel_ms / 1000
        scaled_parallel_s = parallel_s * scale
        table.add_row(
            "Duration (parallel)",
            f"{parallel_s:.2f}s",
            f"{scaled_parallel_s:.2f}s ({scaled_parallel_s/60:.1f}m)",
        )

    # API calls
    if result.api_calls_estimated:
        table.add_row("", "", "")  # Separator
        for api, count in result.api_calls_estimated.items():
            table.add_row(f"API: {api}", str(count), f"{count * scale:,}")

    # Cost
    if result.cost_estimate_usd > 0:
        table.add_row("", "", "")  # Separator
        scaled_cost = result.cost_estimate_usd * scale
        table.add_row(
            "Estimated Cost",
            f"${result.cost_estimate_usd:.4f}",
            f"${scaled_cost:,.2f}",
        )

    console.print(table)


def _display_estimate_result_plain(result, scale: int):
    """Display estimate result in plain text."""
    print("Estimation Complete")
    print(f"\nDuration: {result.estimated_duration_ms/1000:.2f}s")

    if scale > 1:
        scaled_duration = (result.estimated_duration_ms / 1000) * scale
        print(f"  Scaled (x{scale}): {scaled_duration:.2f}s ({scaled_duration/60:.1f}m)")

    if result.api_calls_estimated:
        print("\nAPI Calls:")
        for api, count in result.api_calls_estimated.items():
            print(f"  {api}: {count}")
            if scale > 1:
                print(f"    Scaled (x{scale}): {count * scale:,}")

    if result.cost_estimate_usd > 0:
        print(f"\nEstimated Cost: ${result.cost_estimate_usd:.4f}")
        if scale > 1:
            print(f"  Scaled (x{scale}): ${result.cost_estimate_usd * scale:,.2f}")


def _display_trace_result_rich(result, show_context: bool):
    """Display trace result with Rich formatting."""
    console.print(Panel("[green]Trace Complete[/green]", title="Success"))

    for idx, event in enumerate(result.trace, 1):
        console.print(f"\n[bold cyan]Step {idx}: {event.step_name}[/bold cyan]")
        console.print(f"  Action: {event.action}")
        console.print(f"  Duration: {event.estimated_duration_ms}ms")

        if show_context:
            console.print("  Context changes:")
            # Show only new/changed keys
            before_keys = set(event.context_before.keys())
            after_keys = set(event.context_after.keys())
            new_keys = after_keys - before_keys

            if new_keys:
                for key in new_keys:
                    console.print(f"    [green]+[/green] {key}: {event.context_after[key]}")


def _display_trace_result_plain(result, show_context: bool):
    """Display trace result in plain text."""
    print("Trace Complete\n")

    for idx, event in enumerate(result.trace, 1):
        print(f"Step {idx}: {event.step_name}")
        print(f"  Action: {event.action}")
        print(f"  Duration: {event.estimated_duration_ms}ms")

        if show_context:
            before_keys = set(event.context_before.keys())
            after_keys = set(event.context_after.keys())
            new_keys = after_keys - before_keys

            if new_keys:
                print("  Context changes:")
                for key in new_keys:
                    print(f"    + {key}: {event.context_after[key]}")
        print()
