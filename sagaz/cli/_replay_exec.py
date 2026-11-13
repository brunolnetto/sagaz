"""Async execution of the replay, time-travel and list-changes operations.

Output goes through ``replay_ui`` with the dependencies returned by
``sagaz.cli.replay._ui_kwargs``, looked up at call time so that patching
``sagaz.cli.replay.HAS_RICH`` / ``console`` / ``click`` keeps taking effect.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import click

from sagaz.cli import replay_ui

if TYPE_CHECKING:
    from sagaz.core.replay.saga_replay import ReplayResult, SagaReplay
    from sagaz.core.replay.time_travel import HistoricalState


def _ui_kwargs() -> dict[str, Any]:
    """Output dependencies for replay_ui, resolved through ``sagaz.cli.replay``."""
    from sagaz.cli import replay as cli_replay

    return cli_replay._ui_kwargs()


async def _show_checkpoints(replay: "SagaReplay", verbose: bool):
    """Display available checkpoints."""
    if not verbose:
        return

    checkpoints = await replay.list_available_checkpoints()
    replay_ui.show_checkpoints(checkpoints, verbose, **_ui_kwargs())


def _show_replay_result(result: "ReplayResult", verbose: bool, dry_run: bool):
    """Display replay result."""
    replay_ui.show_replay_result(result, verbose, dry_run, **_ui_kwargs())


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


def _display_key_value(key: str, value: Any, output_format: str):
    """Display a key-value pair."""
    replay_ui.display_key_value(key, value, output_format, echo_func=click.echo)


def _display_full_state(state: "HistoricalState", output_format: str):
    """Display full saga state."""
    replay_ui.display_full_state(state, output_format, **_ui_kwargs())


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

    replay_ui.display_changes(changes, saga_id, **_ui_kwargs())
