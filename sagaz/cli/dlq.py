"""
Sagaz CLI — Dead Letter Queue (DLQ) commands.

Provides inspection and recovery operations for outbox events that have
exhausted their retry budget and were parked in the dead letter queue.
"""

from __future__ import annotations

import asyncio
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
    """Return the default in-memory outbox storage.

    In a real deployment this would be resolved from a project config or
    environment variables.  For CLI use we fall back to an ephemeral
    in-memory store so the commands are always importable.
    """
    from sagaz.core.storage.backends.memory.outbox import InMemoryOutboxStorage

    return InMemoryOutboxStorage()


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
        cutoff = _parse_duration(older_than) if older_than else None
        count = await storage.purge_dead_letter_events(older_than=cutoff)
        click.echo(f"Purged {count} DLQ event(s).")

    asyncio.run(_run())
