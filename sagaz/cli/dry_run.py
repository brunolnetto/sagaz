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
    "--saga", "-s", type=str, default=None, help="Specific saga name to validate (interactive if omitted)"
)
@click.option(
    "--context", "-c", type=str, default="{}", help="Context JSON (default: {})"
)
def validate_cmd(saga: str | None, context: str):
    """
    Validate saga configuration for project.
    
    Discovers sagas from sagaz.yaml paths and validates them.
    If no --saga specified, presents interactive selection.
    
    \b
    Examples:
        sagaz validate                    # Interactive selection
        sagaz validate --saga OrderSaga   # Validate specific saga
        sagaz validate --context='{"order_id": "123"}'
    """
    import asyncio

    ctx = json.loads(context)

    # Discover sagas from project
    sagas = _discover_project_sagas()
    
    if not sagas:
        click.echo("Error: No sagas found in project. Check sagaz.yaml paths.", err=True)
        click.echo("   Have you run 'sagaz init' yet?", err=True)
        sys.exit(1)
    
    # Interactive selection if no saga specified
    if not saga:
        saga = _interactive_saga_selection(sagas, "validate")
        if not saga:
            click.echo("Aborted.")
            sys.exit(0)
    
    # Filter to specific saga
    sagas = [s for s in sagas if s["name"] == saga]
    if not sagas:
        click.echo(f"Error: Saga '{saga}' not found in project", err=True)
        sys.exit(1)

    # Run validation for selected saga
    engine = DryRunEngine()
    all_success = True
    results = []
    
    for saga_info in sagas:
        saga_instance = saga_info["class"]()
        result = asyncio.run(engine.run(saga_instance, ctx, DryRunMode.VALIDATE))
        results.append((saga_info["name"], result))
        if not result.success:
            all_success = False

    # Display results
    if RICH_AVAILABLE and console:
        _display_project_validation_results_rich(results)
    else:
        _display_project_validation_results_plain(results)

    sys.exit(0 if all_success else 1)


@click.command(name="simulate")
@click.option(
    "--saga", "-s", type=str, default=None, help="Specific saga name to simulate (interactive if omitted)"
)
@click.option(
    "--context", "-c", type=str, default="{}", help="Context JSON (default: {})"
)
@click.option(
    "--show-parallel", "-p", is_flag=True, help="Show parallel execution groups"
)
def simulate_cmd(saga: str | None, context: str, show_parallel: bool):
    """
    Simulate saga execution and show step order.
    
    Analyzes execution DAG and parallelization for project sagas.
    If no --saga specified, presents interactive selection.
    
    \b
    Examples:
        sagaz simulate                     # Interactive selection
        sagaz simulate --saga OrderSaga    # Simulate specific saga
        sagaz simulate --show-parallel     # Show parallel groups
    """
    import asyncio

    ctx = json.loads(context)

    # Discover sagas from project
    sagas = _discover_project_sagas()
    
    if not sagas:
        click.echo("Error: No sagas found in project. Check sagaz.yaml paths.", err=True)
        click.echo("   Have you run 'sagaz init' yet?", err=True)
        sys.exit(1)
    
    # Interactive selection if no saga specified
    if not saga:
        saga = _interactive_saga_selection(sagas, "simulate")
        if not saga:
            click.echo("Aborted.")
            sys.exit(0)
    
    # Filter to specific saga
    sagas = [s for s in sagas if s["name"] == saga]
    if not sagas:
        click.echo(f"Error: Saga '{saga}' not found in project", err=True)
        sys.exit(1)

    # Run simulation for selected saga
    engine = DryRunEngine()
    all_success = True
    results = []
    
    for saga_info in sagas:
        saga_instance = saga_info["class"]()
        result = asyncio.run(engine.run(saga_instance, ctx, DryRunMode.SIMULATE))
        
        if not result.success:
            all_success = False
            
        results.append((saga_info["name"], result))

    # Display simulation results
    if RICH_AVAILABLE and console:
        _display_project_simulation_results_rich(results, show_parallel)
    else:
        _display_project_simulation_results_plain(results, show_parallel)
    
    sys.exit(0 if all_success else 1)


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
    click.echo(f"  0. Cancel")
    
    choice = click.prompt(
        "Choice",
        type=click.IntRange(0, len(sagas)),
        default=1
    )
    
    if choice == 0:
        return None
    
    return sagas[choice - 1]["name"]


def _discover_project_sagas():
    """Discover sagas from project sagaz.yaml configuration."""
    import yaml
    from pathlib import Path
    
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
        if not p.exists():
            continue
        
        for file_path in p.rglob("*.py"):
            if file_path.name.startswith("__"):
                continue
                
            try:
                module_name = f"sagaz_user_code.{file_path.stem}"
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if not (spec and spec.loader):
                    continue
                
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, Saga) and obj is not Saga:
                        discovered.append({
                            "name": name,
                            "file": str(file_path),
                            "class": obj
                        })
            except Exception:
                pass
    
    return discovered


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
    console.print(Panel("[green]DAG Analysis Complete[/green]", title="Success"))
    
    # Show forward execution layers
    console.print("\n[bold cyan]Forward Execution Layers (Parallelizable Groups):[/bold cyan]")
    for layer in result.forward_layers:
        console.print(f"\n[yellow]Layer {layer.layer_number}:[/yellow]")
        for step in layer.steps:
            console.print(f"  • {step}")
        if layer.dependencies:
            console.print(f"  [dim]Depends on: {', '.join(sorted(layer.dependencies))}[/dim]")
    
    # Show parallelization analysis
    console.print("\n[bold cyan]Parallelization Analysis:[/bold cyan]")
    table = Table(show_header=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Total steps", str(len(result.steps_planned)))
    table.add_row("Sequential layers", str(result.total_layers))
    table.add_row("Max parallel width", f"{result.max_parallel_width} step(s) per layer")
    table.add_row("Parallelization ratio", f"{result.parallelization_ratio:.2f}")
    table.add_row("Critical path length", f"{len(result.critical_path)} step(s)")
    
    console.print(table)
    
    # Show critical path
    if result.critical_path:
        console.print("\n[bold cyan]Critical Path (Longest Chain):[/bold cyan]")
        console.print(" → ".join(result.critical_path))
    
    # Show backward compensation layers
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
    print("DAG Analysis Complete\n")
    
    print("Forward Execution Layers (Parallelizable Groups):\n")
    for layer in result.forward_layers:
        print(f"Layer {layer.layer_number}:")
        for step in layer.steps:
            print(f"  • {step}")
        if layer.dependencies:
            print(f"  Depends on: {', '.join(sorted(layer.dependencies))}")
        print()
    
    print("Parallelization Analysis:")
    print(f"  Total steps: {len(result.steps_planned)}")
    print(f"  Sequential layers: {result.total_layers}")
    print(f"  Max parallel width: {result.max_parallel_width} step(s) per layer")
    print(f"  Parallelization ratio: {result.parallelization_ratio:.2f}")
    print(f"  Critical path length: {len(result.critical_path)} step(s)")
    
    if result.critical_path:
        print(f"\nCritical Path: {' → '.join(result.critical_path)}")
    
    if result.backward_layers:
        print("\nCompensation Layers (Rollback Order):")
        for layer in result.backward_layers:
            print(f"\nLayer {layer.layer_number}:")
            for step in layer.steps:
                print(f"  • {step}")


def _display_project_validation_results_rich(results):
    """Display validation results for multiple sagas with Rich formatting."""
    all_success = all(result.success for _, result in results)
    
    if all_success:
        console.print(Panel("[green]✓ All sagas validated successfully[/green]", title="Success"))
    else:
        console.print(Panel("[red]✗ Some sagas failed validation[/red]", title="Error"))
    
    for saga_name, result in results:
        console.print(f"\n[bold cyan]Saga: {saga_name}[/bold cyan]")
        
        if result.success:
            if result.validation_checks:
                table = Table(show_header=True)
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
            console.print("[red]Errors:[/red]")
            for error in result.validation_errors:
                console.print(f"  • {error}")
            
            if result.validation_warnings:
                console.print("\n[yellow]⚠ Warnings:[/yellow]")
                for warning in result.validation_warnings:
                    console.print(f"  • {warning}")


def _display_project_validation_results_plain(results):
    """Display validation results for multiple sagas in plain text."""
    all_success = all(result.success for _, result in results)
    
    if all_success:
        print("✓ All sagas validated successfully\n")
    else:
        print("✗ Some sagas failed validation\n")
    
    for saga_name, result in results:
        print(f"\nSaga: {saga_name}")
        
        if result.success:
            print("  ✓ Validation passed")
            if result.validation_warnings:
                print("\nWarnings:")
                for warning in result.validation_warnings:
                    print(f"  • {warning}")
        else:
            print("  ✗ Validation failed")
            print("\nErrors:")
            for error in result.validation_errors:
                print(f"  • {error}")
            
            if result.validation_warnings:
                print("\nWarnings:")
                for warning in result.validation_warnings:
                    print(f"  • {warning}")


def _display_project_simulation_results_rich(results, show_parallel: bool):
    """Display simulation results for multiple sagas with Rich formatting."""
    all_success = all(result.success for _, result in results)
    
    if all_success:
        console.print(Panel("[green]✓ All sagas simulated successfully[/green]", title="Success"))
    else:
        console.print(Panel("[yellow]⚠ Some sagas had issues[/yellow]", title="Warning"))
    
    for saga_name, result in results:
        console.print(f"\n[bold cyan]═══ Saga: {saga_name} ═══[/bold cyan]")
        
        if not result.success:
            console.print("[red]Validation failed - cannot simulate[/red]")
            for error in result.validation_errors:
                console.print(f"  • {error}")
            continue
        
        # Show forward execution layers
        console.print("\n[bold]Forward Execution Layers (Parallelizable Groups):[/bold]")
        for layer in result.forward_layers:
            console.print(f"\n[yellow]Layer {layer.layer_number}:[/yellow]")
            for step in layer.steps:
                console.print(f"  • {step}")
            if layer.dependencies:
                console.print(f"  [dim]Depends on: {', '.join(sorted(layer.dependencies))}[/dim]")
        
        # Show parallelization analysis
        console.print("\n[bold]Parallelization Analysis:[/bold]")
        table = Table(show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total steps", str(len(result.steps_planned)))
        table.add_row("Sequential layers", str(result.total_layers))
        table.add_row("Max parallel width", f"{result.max_parallel_width} step(s) per layer")
        table.add_row("Parallelization ratio", f"{result.parallelization_ratio:.2f}")
        table.add_row("Critical path length", f"{len(result.critical_path)} step(s)")
        
        console.print(table)
        
        # Show critical path
        if result.critical_path:
            console.print("\n[bold]Critical Path (Longest Chain):[/bold]")
            console.print(" → ".join(result.critical_path))
        
        # Show backward compensation layers
        if result.backward_layers:
            console.print("\n[bold]Compensation Layers (Rollback Order):[/bold]")
            for layer in result.backward_layers:
                console.print(f"\n[yellow]Layer {layer.layer_number}:[/yellow]")
                for step in layer.steps:
                    console.print(f"  • {step}")
        
        # Show old-style parallel groups if requested (backward compatibility)
        if show_parallel and result.parallel_groups:
            console.print("\n[dim]Legacy Parallel Groups (for reference):[/dim]")
            for idx, group in enumerate(result.parallel_groups):
                console.print(f"[dim]  Group {idx}: {', '.join(group)}[/dim]")


def _display_project_simulation_results_plain(results, show_parallel: bool):
    """Display simulation results for multiple sagas in plain text."""
    all_success = all(result.success for _, result in results)
    
    if all_success:
        print("✓ All sagas simulated successfully\n")
    else:
        print("⚠ Some sagas had issues\n")
    
    for saga_name, result in results:
        print(f"\n═══ Saga: {saga_name} ═══")
        
        if not result.success:
            print("Validation failed - cannot simulate")
            for error in result.validation_errors:
                print(f"  • {error}")
            continue
        
        print("\nForward Execution Layers (Parallelizable Groups):")
        for layer in result.forward_layers:
            print(f"\nLayer {layer.layer_number}:")
            for step in layer.steps:
                print(f"  • {step}")
            if layer.dependencies:
                print(f"  Depends on: {', '.join(sorted(layer.dependencies))}")
        
        print("\nParallelization Analysis:")
        print(f"  Total steps: {len(result.steps_planned)}")
        print(f"  Sequential layers: {result.total_layers}")
        print(f"  Max parallel width: {result.max_parallel_width} step(s) per layer")
        print(f"  Parallelization ratio: {result.parallelization_ratio:.2f}")
        print(f"  Critical path length: {len(result.critical_path)} step(s)")
        
        if result.critical_path:
            print(f"\nCritical Path: {' → '.join(result.critical_path)}")
        
        if result.backward_layers:
            print("\nCompensation Layers (Rollback Order):")
            for layer in result.backward_layers:
                print(f"\nLayer {layer.layer_number}:")
                for step in layer.steps:
                    print(f"  • {step}")



