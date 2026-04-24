"""
Sagaz CLI - Replay Commands

Commands for saga replay and time-travel operations.
Refactored to reduce complexity and decouple UI logic (v1.6.1).
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import click

from sagaz.cli.replay_ui import (
    HAS_RICH as _HAS_RICH_UI,
)
from sagaz.cli.replay_ui import (
    console as _CONSOLE_UI,
)
from sagaz.cli.replay_ui import (
    display_changes,
    display_failure,
    display_full_state,
    display_key_value,
    display_replay_config,
    display_success,
    handle_exception,
    show_checkpoints,
    show_replay_result,
)

try:
    from rich.console import Console
    from rich.json import JSON
    from rich.panel import Panel
    from rich.table import Table
    _console = Console()
    HAS_RICH = True
except ImportError:
    _console = None
    HAS_RICH = False
    JSON = None
    Panel = None
    Table = None

# For backward compatibility with modules that import it
console = _console

# Backwards compatibility for tests (proper functions to capture patched HAS_RICH and click.echo)
def _display_replay_config(*args, **kwargs):
    return display_replay_config(*args, rich_available=HAS_RICH, echo_func=click.echo, console=console, **kwargs)

def _display_success(*args, **kwargs):
    return display_success(*args, rich_available=HAS_RICH, echo_func=click.echo, console=console, **kwargs)

def _display_failure(*args, **kwargs):
    return display_failure(*args, rich_available=HAS_RICH, echo_func=click.echo, console=console, **kwargs)

def _handle_exception(*args, **kwargs):
    return handle_exception(*args, rich_available=HAS_RICH, echo_func=click.echo, console=console, **kwargs)

def _show_checkpoints(*args, **kwargs):
    return show_checkpoints(*args, rich_available=HAS_RICH, echo_func=click.echo, console=console, **kwargs)

def _show_replay_result(*args, **kwargs):
    return show_replay_result(*args, rich_available=HAS_RICH, echo_func=click.echo, console=console, **kwargs)

def _display_key_value(*args, **kwargs):
    return display_key_value(*args, echo_func=click.echo, **kwargs)

def _display_full_state(*args, **kwargs):
    return display_full_state(*args, rich_available=HAS_RICH, echo_func=click.echo, console=console, **kwargs)

def _display_changes(*args, **kwargs):
    return display_changes(*args, rich_available=HAS_RICH, echo_func=click.echo, console=console, **kwargs)

def _display_state_table(*args, **kwargs):
    return _display_full_state(*args, output_format="table", **kwargs)


@click.group()
def replay():
    """Saga replay and time-travel commands"""


@replay.command("run")
@click.argument("saga_id")
@click.option("--from-step", "-s", required=True, help="Step name to resume from")
@click.option(
    "--storage",
    "-t",
    default="memory",
    type=click.Choice(["memory", "redis", "postgres"]),
    help="Snapshot storage backend",
)
@click.option("--storage-url", help="Storage connection URL (for redis/postgres)")
@click.option("--override", "-o", multiple=True, help="Context overrides (format: key=value)")
@click.option("--dry-run", "-d", is_flag=True, help="Validate without executing")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def replay_command(
    saga_id: str,
    from_step: str,
    storage: str,
    storage_url: str | None,
    override: tuple[str, ...],
    dry_run: bool,
    verbose: bool,
):
    """Replay a saga from a checkpoint."""
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


@replay.command("time-travel")
@click.argument("saga_id")
@click.option("--at", "-t", required=True, help="Timestamp to query (ISO format)")
@click.option(
    "--storage",
    "-s",
    default="memory",
    type=click.Choice(["memory", "redis", "postgres"]),
    help="Snapshot storage backend",
)
@click.option("--storage-url", help="Storage connection URL")
@click.option("--key", "-k", help="Specific context key to query")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["json", "table", "text"]),
    default="text",
    help="Output format",
)
def time_travel_command(saga_id: str, at: str, storage: str, storage_url: str | None, key: str | None, output_format: str):
    """Query saga state at a specific point in time."""
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
            _execute_time_travel(saga_uuid, timestamp, storage, storage_url, key, output_format)
        )
        return 0 if result else 1

    except Exception as e:
        _handle_exception(e, False)
        return 1


@replay.command("list-changes")
@click.argument("saga_id")
@click.option("--after", "-a", help="Show changes after time")
@click.option("--before", "-b", help="Show changes before time")
@click.option("--limit", "-l", type=int, default=100, help="Max changes to show")
@click.option(
    "--storage",
    "-s",
    default="memory",
    type=click.Choice(["memory", "redis", "postgres"]),
    help="Snapshot storage backend",
)
def list_changes_command(saga_id: str, after: str | None, before: str | None, limit: int, storage: str):
    """List all state changes for a saga."""
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
        _handle_exception(e, False)
        return 1


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
    from sagaz.core.replay.saga_replay import SagaReplay

    # Create storage
    if storage_type == "memory":
        from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage
        storage = InMemorySnapshotStorage()
    else:
        msg = f"Storage type '{storage_type}' not yet supported"
        raise NotImplementedError(msg)

    # Create replay instance
    replay_obj = SagaReplay(
        saga_id=saga_id,
        snapshot_storage=storage,
    )

    # List available checkpoints
    if verbose:
        checkpoints = await replay_obj.list_available_checkpoints()
        _show_checkpoints(checkpoints, verbose)

    # Execute replay
    result = await replay_obj.from_checkpoint(
        step_name=from_step,
        context_override=context_override or None,
        dry_run=dry_run,
    )

    # Show result
    _show_replay_result(result, verbose, dry_run)

    return result.replay_status.value == "success"


async def _execute_time_travel(
    saga_id: UUID,
    timestamp: datetime,
    storage_type: str,
    storage_url: str | None,
    key: str | None,
    output_format: str,
) -> bool:
    """Execute time-travel query"""
    from sagaz.core.replay.time_travel import SagaTimeTravel

    # Create storage
    if storage_type == "memory":
        from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage
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


async def _execute_list_changes(
    saga_id: UUID,
    after: datetime | None,
    before: datetime | None,
    limit: int,
    storage_type: str,
):
    """Execute list changes query"""
    from sagaz.core.replay.time_travel import SagaTimeTravel

    # Create storage
    if storage_type == "memory":
        from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage
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

    _display_changes(changes, saga_id)
