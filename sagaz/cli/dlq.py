"""
Sagaz CLI — Dead Letter Queue (DLQ) commands.

Provides inspection and recovery operations for outbox events that have
exhausted their retry budget and were parked in the dead letter queue.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import click

try:
    from rich.console import Console
    from rich.table import Table

    console: Console | None = Console()
except ImportError:
    console = None
    Table = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_duration(value: str) -> timedelta:
    """Parse a simple duration string, e.g. '7d', '24h', '30m'."""
    unit = value[-1].lower()
    amount = int(value[:-1])
    if unit == "d":
        return timedelta(days=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    msg = f"Unsupported duration unit '{unit}'. Use d/h/m (e.g. 7d, 24h, 30m)."
    raise click.BadParameter(msg)


def _get_storage():
    """Resolve outbox storage from environment, with in-memory fallback."""
    from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage
    from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage
    from sagaz.core.storage.backends.redis.outbox import RedisOutboxStorage
    from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage

    outbox_url = (
        os.getenv("SAGAZ_OUTBOX_URL")
        or os.getenv("OUTBOX_URL")
        or os.getenv("SAGAZ_STORAGE_URL")
        or os.getenv("DATABASE_URL")
    )

    if not outbox_url or outbox_url == "memory://":
        return InMemoryOutboxStorage()

    if outbox_url.startswith("redis://"):
        return RedisOutboxStorage(redis_url=outbox_url)

    if outbox_url.startswith(("postgresql://", "postgres://")):
        return PostgreSQLOutboxStorage(connection_string=outbox_url)

    if outbox_url.startswith("sqlite://"):
        db_path = outbox_url.replace("sqlite://", "", 1) or ":memory:"
        return SQLiteOutboxStorage(db_path=db_path)

    msg = f"Unsupported outbox URL: {outbox_url}"
    raise click.ClickException(msg)


async def _initialize_storage(storage) -> None:
    initialize = getattr(storage, "initialize", None)
    if callable(initialize):
        await initialize()


async def _close_storage(storage) -> None:
    close = getattr(storage, "close", None)
    if callable(close):
        await close()


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------


@click.group(name="dlq")
def dlq_cli() -> None:
    """Manage the Dead Letter Queue (DLQ) for outbox events."""


# ---------------------------------------------------------------------------
# dlq list
# ---------------------------------------------------------------------------


@dlq_cli.command(name="list")
@click.option("--limit", default=100, show_default=True, help="Maximum events to display.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
    help="Output format.",
)
def dlq_list(limit: int, output_format: str) -> None:
    """List events currently in the Dead Letter Queue."""

    async def _run() -> None:
        storage = _get_storage()
        await _initialize_storage(storage)
        try:
            events = await storage.get_dead_letter_events(limit=limit)

            if not events:
                click.echo("Dead letter queue is empty.")
                return

            if output_format == "json":
                import json

                click.echo(json.dumps([e.to_dict() for e in events], indent=2, default=str))
                return

            if console and Table:
                table = Table(title=f"Dead Letter Queue ({len(events)} event(s))")
                table.add_column("Event ID", style="dim")
                table.add_column("Saga ID")
                table.add_column("Event Type")
                table.add_column("Retries", justify="right")
                table.add_column("DL Reason")
                table.add_column("DL At")
                for e in events:
                    table.add_row(
                        e.event_id[:8] + "…",
                        e.saga_id,
                        e.event_type,
                        str(e.retry_count),
                        e.dead_letter_reason or "-",
                        e.dead_letter_at.isoformat() if e.dead_letter_at else "-",
                    )
                console.print(table)
            else:
                for e in events:
                    click.echo(
                        f"{e.event_id}  {e.saga_id}  {e.event_type}  "
                        f"retries={e.retry_count}  reason={e.dead_letter_reason}"
                    )
        finally:
            await _close_storage(storage)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# dlq replay
# ---------------------------------------------------------------------------


@dlq_cli.command(name="replay")
@click.option("--id", "event_id", default=None, help="Re-queue a single event by ID.")
@click.option("--all", "replay_all", is_flag=True, default=False, help="Re-queue all DLQ events.")
def dlq_replay(event_id: str | None, replay_all: bool) -> None:
    """Re-queue Dead Letter Queue events for reprocessing."""
    if not event_id and not replay_all:
        msg = "Provide --id <event-id> or --all."
        raise click.UsageError(msg)

    async def _run() -> None:
        storage = _get_storage()
        await _initialize_storage(storage)
        try:
            if replay_all:
                events = await storage.get_dead_letter_events(limit=10_000)
                count = 0
                for e in events:
                    await storage.requeue_dead_letter_event(e.event_id)
                    count += 1
                click.echo(f"Re-queued {count} event(s).")
                return

            try:
                requeued = await storage.requeue_dead_letter_event(event_id)  # type: ignore[arg-type]
                click.echo(f"Re-queued event {requeued.event_id} (saga {requeued.saga_id}).")
            except KeyError:
                msg = f"Event '{event_id}' not found in DLQ."
                raise click.ClickException(msg)
        finally:
            await _close_storage(storage)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# dlq purge
# ---------------------------------------------------------------------------


@dlq_cli.command(name="purge")
@click.option(
    "--older",
    "older_than",
    default=None,
    help="Only purge events older than this duration (e.g. 7d, 24h, 30m). "
    "Omit to purge all DLQ events.",
)
@click.confirmation_option(prompt="Purge DLQ events — are you sure?")
def dlq_purge(older_than: str | None) -> None:
    """Permanently remove events from the Dead Letter Queue."""

    async def _run() -> None:
        storage = _get_storage()
        await _initialize_storage(storage)
        try:
            cutoff = _parse_duration(older_than) if older_than else None
            count = await storage.purge_dead_letter_events(older_than=cutoff)
            click.echo(f"Purged {count} DLQ event(s).")
        finally:
            await _close_storage(storage)

    asyncio.run(_run())
