"""
Sagaz CLI - Replay Commands

Commands for saga replay and time-travel operations.
"""

import asyncio
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import click

try:
    from rich.console import Console
    from rich.json import JSON
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.table import Table

    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False

if TYPE_CHECKING:
    from sagaz.core.saga_replay import ReplayResult, SagaReplay
    from sagaz.core.time_travel import SagaHistoricalState


# ============================================================================
# Replay Command Group
# ============================================================================


@click.group()
def replay():
    """Saga replay and time-travel commands"""


# ============================================================================
# Replay Command
# ============================================================================


@replay.command("run")
@click.argument("saga_id")
@click.option(
    "--from-step",
    "-s",
    required=True,
    help="Step name to resume from",
)
@click.option(
    "--storage",
    "-t",
    default="memory",
    type=click.Choice(["memory", "redis", "postgres"]),
    help="Snapshot storage backend",
)
@click.option(
    "--storage-url",
    help="Storage connection URL (for redis/postgres)",
)
@click.option(
    "--override",
    "-o",
    multiple=True,
    help="Context overrides (format: key=value)",
)
@click.option(
    "--dry-run",
    "-d",
    is_flag=True,
    help="Validate without executing",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Verbose output",
)
def _parse_overrides(override_tuple: tuple[str, ...]) -> dict[str, str]:
    """Parse override key=value pairs."""
    context_override = {}
    for override_str in override_tuple:
        if "=" not in override_str:
            msg = f"Invalid override format: {override_str}"
            click.echo(
                f"Error: {msg}. Use key=value",
                err=True,
            )
            raise ValueError(msg)
        key, value = override_str.split("=", 1)
        context_override[key] = value
    return context_override


def _display_replay_config(
    saga_id: str,
    from_step: str,
    storage: str,
    context_override: dict,
    dry_run: bool,
):
    """Display replay configuration."""
    if HAS_RICH and console:
        console.print(
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
        click.echo(f"Replaying saga {saga_id} from step {from_step}...")


def _display_success():
    """Display success message."""
    if HAS_RICH and console:
        console.print("[green]✓ Replay completed successfully[/green]")
    else:
        click.echo("✓ Replay completed successfully")


def _display_failure():
    """Display failure message."""
    if HAS_RICH and console:
        console.print("[red]✗ Replay failed[/red]")
    else:
        click.echo("✗ Replay failed", err=True)


def _handle_exception(e: Exception, verbose: bool):
    """Handle and display exception."""
    if HAS_RICH and console:
        console.print(f"[red]Error: {e}[/red]")
    else:
        click.echo(f"Error: {e}", err=True)
    if verbose:
        import traceback

        traceback.print_exc()


def replay_command(
    saga_id: str,
    from_step: str,
    storage: str,
    storage_url: str | None,
    override: tuple[str, ...],
    dry_run: bool,
    verbose: bool,
):
    """
    Replay a saga from a checkpoint.

    Example:
        sagaz replay abc-123 --from-step payment --override payment_token=new_token
    """
    # Parse saga_id
    try:
        saga_uuid = UUID(saga_id)
    except ValueError:
        click.echo(f"Error: Invalid saga ID: {saga_id}", err=True)
        return 1

    # Parse overrides
    try:
        context_override = _parse_overrides(override)
    except ValueError:
        return 1

    # Show what we're doing
    _display_replay_config(saga_id, from_step, storage, context_override, dry_run)

    # Execute replay
    try:
        result = asyncio.run(
            _execute_replay(
                saga_uuid,
                from_step,
                storage,
                storage_url,
                context_override,
                dry_run,
                verbose,
            )
        )

        if result:
            _display_success()
            return 0

        _display_failure()
        return 1

    except Exception as e:
        _handle_exception(e, verbose)
        return 1


async def _show_checkpoints(replay: "SagaReplay", verbose: bool):
    """Display available checkpoints."""
    if not verbose:
        return

    checkpoints = await replay.list_available_checkpoints()
    if HAS_RICH and console:
        table = Table(title="Available Checkpoints")
        table.add_column("Step", style="cyan")
        table.add_column("Created At", style="green")
        for cp in checkpoints:
            table.add_row(cp["step_name"], cp["created_at"])
        console.print(table)
    else:
        click.echo("\nAvailable checkpoints:")
        for cp in checkpoints:
            click.echo(f"  - {cp['step_name']} at {cp['created_at']}")


def _show_replay_result(result: "ReplayResult", verbose: bool, dry_run: bool):
    """Display replay result."""
    if not (verbose or dry_run):
        return

    if HAS_RICH and console:
        console.print(
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
        click.echo(f"\nReplay status: {result.replay_status.value}")
        click.echo(f"Original saga ID: {result.original_saga_id}")
        click.echo(f"New saga ID: {result.new_saga_id}")
        if result.error_message:
            click.echo(f"Error: {result.error_message}")


async def _execute_replay(
    saga_id: UUID,
    from_step: str,
    storage_type: str,
    storage_url: str | None,
    context_override: dict,
    dry_run: bool,
    verbose: bool,
) -> bool:
    """Execute the replay operation"""
    from sagaz.core.saga_replay import SagaReplay

    # Create storage
    if storage_type == "memory":
        from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage

        storage = InMemorySnapshotStorage()
    else:
        msg = f"Storage type '{storage_type}' not yet supported"
        raise NotImplementedError(msg)

    # Create replay instance
    replay = SagaReplay(
        saga_id=saga_id,
        snapshot_storage=storage,
    )

    # List available checkpoints
    await _show_checkpoints(replay, verbose)

    # Execute replay
    result = await replay.from_checkpoint(
        step_name=from_step,
        context_override=context_override or None,
        dry_run=dry_run,
    )

    # Show result
    _show_replay_result(result, verbose, dry_run)

    return result.replay_status.value == "success"


# ============================================================================
# Time-Travel Command
# ============================================================================


@replay.command("time-travel")
@click.argument("saga_id")
@click.option(
    "--at",
    "-t",
    required=True,
    help="Timestamp to query (ISO format: 2024-01-15T10:30:00Z)",
)
@click.option(
    "--storage",
    "-s",
    default="memory",
    type=click.Choice(["memory", "redis", "postgres"]),
    help="Snapshot storage backend",
)
@click.option(
    "--storage-url",
    help="Storage connection URL (for redis/postgres)",
)
@click.option(
    "--key",
    "-k",
    help="Specific context key to query (returns all if not specified)",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "table", "text"]),
    default="text",
    help="Output format",
)
def time_travel_command(
    saga_id: str,
    at: str,
    storage: str,
    storage_url: str | None,
    key: str | None,
    format: str,
):
    """
    Query saga state at a specific point in time.

    Example:
        sagaz time-travel abc-123 --at 2024-01-15T10:30:00Z
        sagaz time-travel abc-123 --at 2024-01-15T10:30:00Z --key payment_token
    """
    # Parse saga_id
    try:
        saga_uuid = UUID(saga_id)
    except ValueError:
        click.echo(f"Error: Invalid saga ID: {saga_id}", err=True)
        return 1

    # Parse timestamp
    try:
        timestamp = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
    except ValueError:
        click.echo(f"Error: Invalid timestamp format: {at}", err=True)
        click.echo("Use ISO format: 2024-01-15T10:30:00Z", err=True)
        return 1

    # Execute time-travel query
    try:
        result = asyncio.run(
            _execute_time_travel(saga_uuid, timestamp, storage, storage_url, key, format)
        )
        return 0 if result else 1

    except Exception as e:
        if HAS_RICH and console:
            console.print(f"[red]Error: {e}[/red]")
        else:
            click.echo(f"Error: {e}", err=True)
        return 1


def _display_key_value(key: str, value: Any, output_format: str):
    """Display a key-value pair."""
    if output_format == "json":
        import json

        click.echo(json.dumps({key: value}, indent=2))
    else:
        click.echo(f"{key}: {value}")


def _display_full_state(state: "SagaHistoricalState", output_format: str):
    """Display full saga state."""
    if output_format == "json":
        import json

        click.echo(json.dumps(state.to_dict(), indent=2))
    elif output_format == "table" and HAS_RICH and console:
        _display_state_table(state)
    else:
        _display_state_text(state)


def _display_state_table(state: "SagaHistoricalState"):
    """Display state as table (Rich)."""
    table = Table(title=f"Saga State at {state.snapshot_time}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Saga ID", str(state.saga_id))
    table.add_row("Saga Name", state.saga_name)
    table.add_row("Status", state.status)
    table.add_row("Current Step", state.current_step or "N/A")
    table.add_row("Step Index", str(state.step_index))
    table.add_row("Completed Steps", ", ".join(state.completed_steps) or "None")
    console.print(table)

    if state.context:
        console.print("\n[bold]Context:[/bold]")
        console.print(JSON.from_data(state.context))


def _display_state_text(state: "SagaHistoricalState"):
    """Display state as text."""
    click.echo(f"Saga ID: {state.saga_id}")
    click.echo(f"Saga Name: {state.saga_name}")
    click.echo(f"Status: {state.status}")
    click.echo(f"Current Step: {state.current_step}")
    click.echo(f"Step Index: {state.step_index}")
    click.echo(f"Completed Steps: {', '.join(state.completed_steps) or 'None'}")
    click.echo("\nContext:")
    for k, v in state.context.items():
        click.echo(f"  {k}: {v}")


async def _execute_time_travel(
    saga_id: UUID,
    timestamp: datetime,
    storage_type: str,
    storage_url: str | None,
    key: str | None,
    output_format: str,
) -> bool:
    """Execute time-travel query"""
    from sagaz.core.time_travel import SagaTimeTravel

    # Create storage
    if storage_type == "memory":
        from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage

        storage = InMemorySnapshotStorage()
    else:
        msg = f"Storage type '{storage_type}' not yet supported"
        raise NotImplementedError(msg)

    # Create time-travel instance
    time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

    # Query state
    if key:
        # Query specific key
        value = await time_travel.get_context_at(timestamp, key=key)
        if value is None:
            click.echo(f"No state found at {timestamp}")
            return False
        _display_key_value(key, value, output_format)
    else:
        # Query full state
        state = await time_travel.get_state_at(timestamp)
        if not state:
            click.echo(f"No state found at {timestamp}")
            return False
        _display_full_state(state, output_format)

    return True


# ============================================================================
# List Changes Command
# ============================================================================


@replay.command("list-changes")
@click.argument("saga_id")
@click.option(
    "--after",
    "-a",
    help="Only show changes after this time (ISO format)",
)
@click.option(
    "--before",
    "-b",
    help="Only show changes before this time (ISO format)",
)
@click.option(
    "--limit",
    "-l",
    type=int,
    default=100,
    help="Maximum number of changes to show",
)
@click.option(
    "--storage",
    "-s",
    default="memory",
    type=click.Choice(["memory", "redis", "postgres"]),
    help="Snapshot storage backend",
)
def list_changes_command(
    saga_id: str,
    after: str | None,
    before: str | None,
    limit: int,
    storage: str,
):
    """
    List all state changes for a saga.

    Example:
        sagaz list-changes abc-123
        sagaz list-changes abc-123 --after 2024-01-15T10:00:00Z --limit 10
    """
    # Parse saga_id
    try:
        saga_uuid = UUID(saga_id)
    except ValueError:
        click.echo(f"Error: Invalid saga ID: {saga_id}", err=True)
        return 1

    # Parse timestamps
    after_dt = None
    before_dt = None

    if after:
        try:
            after_dt = datetime.fromisoformat(after.replace("Z", "+00:00"))
        except ValueError:
            click.echo(f"Error: Invalid 'after' timestamp: {after}", err=True)
            return 1

    if before:
        try:
            before_dt = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            click.echo(f"Error: Invalid 'before' timestamp: {before}", err=True)
            return 1

    # Execute list changes
    try:
        asyncio.run(_execute_list_changes(saga_uuid, after_dt, before_dt, limit, storage))
        return 0

    except Exception as e:
        if HAS_RICH and console:
            console.print(f"[red]Error: {e}[/red]")
        else:
            click.echo(f"Error: {e}", err=True)
        return 1


async def _execute_list_changes(
    saga_id: UUID,
    after: datetime | None,
    before: datetime | None,
    limit: int,
    storage_type: str,
):
    """Execute list changes query"""
    from sagaz.core.time_travel import SagaTimeTravel

    # Create storage
    if storage_type == "memory":
        from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage

        storage = InMemorySnapshotStorage()
    else:
        msg = f"Storage type '{storage_type}' not yet supported"
        raise NotImplementedError(msg)

    # Create time-travel instance
    time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

    # Query changes
    changes = await time_travel.list_state_changes(after=after, before=before, limit=limit)

    if not changes:
        click.echo("No state changes found")
        return

    # Display changes
    if HAS_RICH and console:
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

        console.print(table)
        console.print(f"\n[dim]Total: {len(changes)} changes[/dim]")
    else:
        click.echo(f"State changes for {saga_id}:")
        for i, change in enumerate(changes, 1):
            click.echo(
                f"{i}. {change.timestamp} - Step: {change.current_step}, "
                f"Status: {change.status}, Completed: {len(change.completed_steps)}"
            )
        click.echo(f"\nTotal: {len(changes)} changes")
