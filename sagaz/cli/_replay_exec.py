"""Async execution of the replay, time-travel and list-changes operations.

Output goes through ``replay_ui`` with the dependencies returned by
``sagaz.cli.replay._ui_kwargs``, looked up at call time so that patching
``sagaz.cli.replay.HAS_RICH`` / ``console`` / ``click`` keeps taking effect.
"""

import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import click

from sagaz.cli import replay_ui

if TYPE_CHECKING:
    from sagaz.core.replay.saga_replay import ReplayResult, SagaReplay
    from sagaz.core.replay.time_travel import HistoricalState, SagaTimeTravel


STORAGE_KINDS = ["redis", "postgres", "filesystem", "memory"]


@asynccontextmanager
async def open_snapshot_storage(kind: str, url: str | None) -> AsyncIterator[Any]:
    """The snapshot storage the saga wrote to (#556): Redis, PostgreSQL or a directory.

    An in-memory storage belongs to the process that wrote it, so the CLI, another
    process, can never see its snapshots.
    """
    if kind == "memory":
        msg = (
            "--storage memory cannot work from the CLI: in-memory snapshots live in the "
            "process that took them. Use --storage redis|postgres|filesystem."
        )
        raise click.UsageError(msg)
    if kind in ("redis", "postgres") and not url:
        msg = f"--storage {kind} needs --storage-url"
        raise click.UsageError(msg)
    if kind == "redis":
        from sagaz.core.storage.backends.redis.snapshot import RedisSnapshotStorage

        storage: Any = RedisSnapshotStorage(redis_url=url or "")
    elif kind == "postgres":
        from sagaz.core.storage.backends.postgresql.snapshot import PostgreSQLSnapshotStorage

        storage = PostgreSQLSnapshotStorage(connection_string=url or "")
    else:
        from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

        storage = FilesystemSnapshotStorage(base_path=url or "./saga-snapshots")
    async with storage:
        yield storage


def load_saga_factory(path: str) -> Any:
    """``module:attr``: a saga class (built with no arguments) or a factory
    ``(saga_name) -> saga``, sync or async, that builds the saga to replay (#556)."""
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        msg = f"--saga takes module:attribute, got {path!r}"
        raise click.UsageError(msg)
    target = getattr(importlib.import_module(module_name), attr)
    if isinstance(target, type):
        return lambda _name: target()
    return target


def _ui_kwargs() -> dict[str, Any]:
    """Output dependencies for replay_ui, resolved through ``sagaz.cli.replay``."""
    from sagaz.cli import replay as cli_replay

    return cli_replay._ui_kwargs()


async def _show_checkpoints(replay: "SagaReplay", verbose: bool) -> None:
    """Display available checkpoints."""
    if not verbose:
        return

    checkpoints = await replay.list_available_checkpoints()
    replay_ui.show_checkpoints(checkpoints, verbose, **_ui_kwargs())


def _show_replay_result(result: "ReplayResult", verbose: bool, dry_run: bool) -> None:
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
    saga_path: str | None = None,
) -> bool:
    """Execute the replay operation"""
    from sagaz.core.replay.saga_replay import SagaReplay

    factory = load_saga_factory(saga_path) if saga_path else None
    async with open_snapshot_storage(storage_type, storage_url) as storage:
        replay = SagaReplay(saga_id=saga_id, snapshot_storage=storage, saga_factory=factory)
        await _show_checkpoints(replay, verbose)
        result = await replay.from_checkpoint(
            step_name=from_step,
            context_override=context_override or None,
            dry_run=dry_run,
        )
    _show_replay_result(result, verbose, dry_run)
    return result.replay_status.value == "success"


def _display_key_value(key: str, value: Any, output_format: str) -> None:
    """Display a key-value pair."""
    replay_ui.display_key_value(key, value, output_format, echo_func=click.echo)


def _display_full_state(state: "HistoricalState", output_format: str) -> None:
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

    async with open_snapshot_storage(storage_type, storage_url) as storage:
        return await _time_travel_query(
            SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage),
            timestamp,
            key,
            output_format,
        )


async def _time_travel_query(
    time_travel: "SagaTimeTravel", timestamp: datetime, key: str | None, output_format: str
) -> bool:
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
    storage_url: str | None = None,
) -> None:
    """Execute list changes query"""
    from sagaz.core.replay.time_travel import SagaTimeTravel

    async with open_snapshot_storage(storage_type, storage_url) as storage:
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)
        changes = await time_travel.list_state_changes(after=after, before=before, limit=limit)

    if not changes:
        click.echo("No state changes found")
        return

    replay_ui.display_changes(changes, saga_id, **_ui_kwargs())
