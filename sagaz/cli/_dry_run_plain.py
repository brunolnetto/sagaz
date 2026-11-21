"""Plain-text rendering of dry-run results, for when ``rich`` is not installed.

Each function prints what its Rich counterpart in ``_dry_run_display`` shows. They are
re-exported by ``sagaz.cli.dry_run``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from sagaz._dry_run_types import DryRunResult


def _print_bullets(title: str, items: list[Any]) -> None:
    if items:
        click.echo(f"\n{title}")
        for item in items:
            click.echo(f"  - {item}")


def _print_checks_plain(checks: dict[str, Any]) -> None:
    """Print the validation checks, one per line."""
    click.echo(f"  Steps defined: {checks.get('step_count', 0)}")
    if checks.get("step_names"):
        click.echo(f"  Step names: {', '.join(checks['step_names'])}")
    click.echo(f"  Has dependencies: {'yes' if checks.get('has_dependencies') else 'no'}")
    click.echo(f"  Has compensation: {'yes' if checks.get('has_compensation') else 'no'}")
    click.echo(f"  Circular dependencies: {'FOUND' if checks.get('has_cycles') else 'none'}")
    if checks.get("required_context_fields"):
        click.echo(f"  Required context: {', '.join(checks['required_context_fields'])}")


def _display_validation_result_plain(result: DryRunResult) -> None:
    """Display validation result in plain text."""
    if result.success:
        click.echo("Validation passed")
        if result.validation_checks:
            _print_checks_plain(result.validation_checks)
    else:
        click.echo("Validation failed")
        _print_bullets("Errors:", result.validation_errors)
    _print_bullets("Warnings:", result.validation_warnings)


def _print_forward_layers_plain(layers: list[Any]) -> None:
    """Print forward execution layers in plain text."""
    click.echo("\nForward execution layers (parallelizable groups):")
    for layer in layers:
        click.echo(f"\nLayer {layer.layer_number}:")
        for step in layer.steps:
            click.echo(f"  - {step}")
        if layer.dependencies:
            click.echo(f"  Depends on: {', '.join(sorted(layer.dependencies))}")


def _print_parallelization_plain(result: DryRunResult) -> None:
    """Print parallelization analysis in plain text."""
    click.echo("\nParallelization analysis:")
    click.echo(f"  Total steps: {len(result.steps_planned)}")
    click.echo(f"  Sequential layers: {result.total_layers}")
    click.echo(f"  Max parallel width: {result.max_parallel_width} step(s) per layer")
    click.echo(f"  Parallelization ratio: {result.parallelization_ratio:.2f}")
    click.echo(f"  Critical path length: {len(result.critical_path)} step(s)")


def _print_paths_plain(result: DryRunResult, show_parallel: bool) -> None:
    """Print the critical path, the compensation layers and, if asked, the old groups."""
    if result.critical_path:
        click.echo("\nCritical path (longest chain):")
        click.echo("  " + " -> ".join(result.critical_path))
    if result.backward_layers:
        click.echo("\nCompensation layers (rollback order):")
        for layer in result.backward_layers:
            click.echo(f"\nLayer {layer.layer_number}:")
            for step in layer.steps:
                click.echo(f"  - {step}")
    if show_parallel and result.parallel_groups:
        click.echo("\nLegacy parallel groups (for reference):")
        for index, group in enumerate(result.parallel_groups):
            click.echo(f"  Group {index}: {', '.join(group)}")


def _display_simulation_result_plain(result: DryRunResult, show_parallel: bool) -> None:
    """Display simulation result in plain text."""
    click.echo("DAG analysis complete")
    _print_forward_layers_plain(result.forward_layers)
    _print_parallelization_plain(result)
    _print_paths_plain(result, show_parallel)


def _display_project_validation_results_plain(results: list[tuple[str, DryRunResult]]) -> None:
    """Display validation results for multiple sagas in plain text."""
    if all(result.success for _, result in results):
        click.echo("All sagas validated successfully")
    else:
        click.echo("Some sagas failed validation")

    for saga_name, result in results:
        click.echo(f"\nsaga_class: {saga_name}")
        if result.success:
            if result.validation_checks:
                _print_checks_plain(result.validation_checks)
        else:
            _print_bullets("Errors:", result.validation_errors)
        _print_bullets("Warnings:", result.validation_warnings)


def _display_project_simulation_results_plain(
    results: list[tuple[str, DryRunResult]], show_parallel: bool
) -> None:
    """Display simulation results for multiple sagas in plain text."""
    if all(result.success for _, result in results):
        click.echo("All sagas simulated successfully")
    else:
        click.echo("Some sagas had issues")

    for saga_name, result in results:
        click.echo(f"\n=== saga_class: {saga_name} ===")
        if not result.success:
            click.echo("Validation failed - cannot simulate")
            for error in result.validation_errors:
                click.echo(f"  - {error}")
            continue
        _print_forward_layers_plain(result.forward_layers)
        _print_parallelization_plain(result)
        _print_paths_plain(result, show_parallel)
