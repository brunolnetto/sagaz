"""
Sagaz CLI - Replay Commands

Commands for saga replay and time-travel operations.

The async executors live in ``_replay_exec`` and are re-exported here.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import click

from sagaz.cli import replay_ui
from sagaz.cli._replay_exec import (
    _display_full_state,
    _display_key_value,
    _execute_list_changes,
    _execute_replay,
    _execute_time_travel,
    _show_checkpoints,
    _show_replay_result,
)
from sagaz.cli.replay_ui import HAS_RICH, console


def _ui_kwargs() -> dict[str, Any]:
    """Output dependencies for replay_ui, resolved at call time so tests can patch them."""
    return {
        "rich_available": bool(HAS_RICH and console),
        "echo_func": click.echo,
        "console": console,
    }


# ============================================================================
# Replay Command Group
# ============================================================================


@click.group()
def replay():
    """Saga replay and time-travel commands"""


# ============================================================================
# Replay Command
# ============================================================================


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
    replay_ui.display_replay_config(
        saga_id, from_step, storage, context_override, dry_run, **_ui_kwargs()
    )


def _display_success():
    """Display success message."""
    replay_ui.display_success(**_ui_kwargs())


def _display_failure():
    """Display failure message."""
    replay_ui.display_failure(**_ui_kwargs())


def _handle_exception(e: Exception, verbose: bool):
    """Handle and display exception."""
    replay_ui.handle_exception(e, verbose, **_ui_kwargs())


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
        sagaz replay run abc-123 --from-step payment --override payment_token=new_token
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
    format: str,  # pylint: disable=redefined-builtin
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
        _handle_exception(e, verbose=False)
        return 1


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
        _handle_exception(e, verbose=False)
        return 1


__all__ = [
    "HAS_RICH",
    "_display_failure",
    "_display_full_state",
    "_display_key_value",
    "_display_replay_config",
    "_display_success",
    "_execute_list_changes",
    "_execute_replay",
    "_execute_time_travel",
    "_handle_exception",
    "_parse_overrides",
    "_show_checkpoints",
    "_show_replay_result",
    "_ui_kwargs",
    "console",
    "list_changes_command",
    "replay",
    "replay_command",
    "time_travel_command",
]
