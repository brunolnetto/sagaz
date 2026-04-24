"""
UI and display logic for replay and time-travel commands.
"""

from typing import Any

import click

try:
    from rich.console import Console
    from rich.json import JSON
    from rich.panel import Panel
    from rich.table import Table

    _console = Console()
    _HAS_RICH = True
except ImportError:
    _console = None
    _HAS_RICH = False
    JSON = None
    Panel = None
    Table = None

# For backward compatibility with modules that import it
HAS_RICH = _HAS_RICH
console = _console


def display_replay_config(
    saga_id: str,
    from_step: str,
    storage: str,
    context_override: dict,
    dry_run: bool,
    rich_available: bool | None = None,
    echo_func=None,
    console=None,
):
    """Display replay configuration."""
    if rich_available is None:
        rich_available = _HAS_RICH

    con = console or _console
    echo = echo_func or click.echo

    if rich_available and con:
        con.print(
            Panel(
                f"[bold]Saga Replay[/bold]\n\n"
                f"Saga ID: {saga_id}\n"
                f"From Step: {from_step}\n"
                f"Storage: {storage}\n"
                f"Overrides: {len(context_override)}\n"
                f"Dry Run: {dry_run}",
                title="Replay Configuration",
                border_style="blue",
            )
        )
    else:
        echo(f"Replaying saga {saga_id} from step {from_step}...")


def display_success(rich_available: bool | None = None, echo_func=None, console=None):
    """Display success message."""
    if rich_available is None:
        rich_available = _HAS_RICH

    con = console or _console
    echo = echo_func or click.echo

    if rich_available and con:
        con.print("[green]✓ Replay completed successfully[/green]")
    else:
        echo("✓ Replay completed successfully")


def display_failure(rich_available: bool | None = None, echo_func=None, console=None):
    """Display failure message."""
    if rich_available is None:
        rich_available = _HAS_RICH

    con = console or _console
    echo = echo_func or click.echo

    if rich_available and con:
        con.print("[red]✗ Replay failed[/red]")
    else:
        echo("✗ Replay failed", err=True)


def handle_exception(
    e: Exception, verbose: bool, rich_available: bool | None = None, echo_func=None, console=None
):
    """Handle and display exception."""
    if rich_available is None:
        rich_available = _HAS_RICH

    con = console or _console
    echo = echo_func or click.echo

    if rich_available and con:
        con.print(f"[red]Error: {e}[/red]")
    else:
        echo(f"Error: {e}", err=True)
    if verbose:
        import traceback

        traceback.print_exc()


def show_checkpoints(
    checkpoints: list,
    verbose: bool,
    rich_available: bool | None = None,
    echo_func=None,
    console=None,
):
    """Display available checkpoints."""
    if not verbose:
        return

    if rich_available is None:
        rich_available = _HAS_RICH

    con = console or _console
    echo = echo_func or click.echo

    if rich_available and con:
        table = Table(title="Available Checkpoints")
        table.add_column("Step", style="cyan")
        table.add_column("Created At", style="green")
        for cp in checkpoints:
            table.add_row(cp["step_name"], cp["created_at"])
        con.print(table)
    else:
        echo("\nAvailable checkpoints:")
        for cp in checkpoints:
            echo(f"  - {cp['step_name']} at {cp['created_at']}")


def show_replay_result(
    result,
    verbose: bool,
    dry_run: bool,
    rich_available: bool | None = None,
    echo_func=None,
    console=None,
):
    """Display replay result."""
    if not (verbose or dry_run):
        return

    if rich_available is None:
        rich_available = _HAS_RICH

    con = console or _console
    echo = echo_func or click.echo

    if rich_available and con:
        con.print(
            Panel(
                f"Status: {result.replay_status.value}\n"
                f"Original Saga ID: {result.original_saga_id}\n"
                f"New Saga ID: {result.new_saga_id}\n"
                f"Checkpoint: {result.checkpoint_step}\n"
                f"Error: {result.error_message or 'None'}",
                title="Replay Result",
                border_style="green" if result.replay_status.value == "success" else "red",
            )
        )
    else:
        echo(f"\nReplay status: {result.replay_status.value}")
        echo(f"Original saga ID: {result.original_saga_id}")
        echo(f"New saga ID: {result.new_saga_id}")
        if result.error_message:
            echo(f"Error: {result.error_message}")


def display_key_value(key: str, value: Any, output_format: str, echo_func=None):
    """Display a key-value pair."""
    echo = echo_func or click.echo
    if output_format == "json":
        import json

        echo(json.dumps({key: value}, indent=2))
    else:
        echo(f"{key}: {value}")


def display_full_state(
    state, output_format: str, rich_available: bool | None = None, echo_func=None, console=None
):
    """Display full saga state."""
    if rich_available is None:
        rich_available = _HAS_RICH

    con = console or _console
    echo = echo_func or click.echo

    if output_format == "json":
        import json

        echo(json.dumps(state.to_dict(), indent=2))
    elif output_format == "table" and rich_available and con:
        _display_state_table(state, console=con)
    else:
        _display_state_text(state, echo_func=echo)


def _display_state_table(state, console=None):
    """Display state as table (Rich)."""
    con = console or _console
    table = Table(title=f"Saga State at {state.timestamp}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Saga ID", str(state.saga_id))
    table.add_row("Saga Name", state.saga_name)
    table.add_row("Status", state.status)
    table.add_row("Current Step", state.current_step or "N/A")
    table.add_row("Step Index", str(state.step_index))
    table.add_row("Completed Steps", ", ".join(state.completed_steps) or "None")
    con.print(table)

    if state.context:
        con.print("\n[bold]Context:[/bold]")
        con.print(JSON.from_data(state.context))


def _display_state_text(state, echo_func=None):
    """Display state as text."""
    echo = echo_func or click.echo
    echo(f"Saga ID: {state.saga_id}")
    echo(f"Saga Name: {state.saga_name}")
    echo(f"Status: {state.status}")
    echo(f"Current Step: {state.current_step}")
    echo(f"Step Index: {state.step_index}")
    echo(f"Completed Steps: {', '.join(state.completed_steps) or 'None'}")
    echo("\nContext:")
    for k, v in state.context.items():
        echo(f"  {k}: {v}")


def display_changes(
    changes: list, saga_id: Any, rich_available: bool | None = None, echo_func=None, console=None
):
    """Display state changes."""
    if rich_available is None:
        rich_available = _HAS_RICH

    con = console or _console
    echo = echo_func or click.echo

    if rich_available and con:
        table = Table(title=f"State Changes for {saga_id}")
        table.add_column("#", style="dim")
        table.add_column("Timestamp", style="cyan")
        table.add_column("Step", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Completed", style="blue")

        for i, change in enumerate(changes, 1):
            table.add_row(
                str(i),
                change.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                change.current_step or "N/A",
                change.status,
                str(len(change.completed_steps)),
            )

        con.print(table)
        con.print(f"\n[dim]Total: {len(changes)} changes[/dim]")
    else:
        echo(f"State changes for {saga_id}:")
        for i, change in enumerate(changes, 1):
            echo(
                f"{i}. {change.timestamp} - Step: {change.current_step}, "
                f"Status: {change.status}, Completed: {len(change.completed_steps)}"
            )
        echo(f"\nTotal: {len(changes)} changes")
