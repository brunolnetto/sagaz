"""``sagaz choreography``: inspect choreographed transactions (ADR-029, #56).

Reads what a :class:`~sagaz.choreography.ChoreographyTracker` saved in the saga
storage given by ``--storage-url`` (or ``SAGAZ_STORAGE_URL``).
"""

from __future__ import annotations

import asyncio
import json

import click

from sagaz.choreography.tracker import TransactionStatus, load_status, stalled_view
from sagaz.core.tenant import DEFAULT_TENANT, tenant_scope


async def _load(storage_url: str, correlation_id: str, tenant: str) -> TransactionStatus | None:
    from sagaz.core.storage import create_storage_manager

    async with create_storage_manager(url=storage_url) as manager:
        with tenant_scope(tenant):
            return await load_status(manager.saga, correlation_id)


def _describe(status: TransactionStatus) -> list[str]:
    lines = [
        f"Transaction {status.correlation_id} (tenant {status.tenant_id}): {status.status}",
        f"  participants: {', '.join(status.participants) or '-'}",
        f"  events: {len(status.events)}",
    ]
    if status.failure:
        failure = status.failure
        lines.append(
            f"  failed: {failure.get('participant')} on {failure.get('failed_event_type')}"
            f" ({failure.get('reason')})"
        )
    for participant, report in sorted(status.compensated_by.items()):
        undone = ", ".join(report.get("undone") or []) or "nothing to undo"
        broken = report.get("failed") or []
        suffix = f"; compensation failed for {', '.join(broken)}" if broken else ""
        lines.append(f"  compensated by {participant}: {undone}{suffix}")
    return lines


@click.group("choreography")
def choreography_cli() -> None:
    """Inspect choreographed (event-driven) transactions."""


@choreography_cli.command("status")
@click.argument("correlation_id")
@click.option(
    "--storage-url",
    envvar="SAGAZ_STORAGE_URL",
    required=True,
    metavar="URL",
    help="Saga storage the ChoreographyTracker writes to (env: SAGAZ_STORAGE_URL).",
)
@click.option(
    "--tenant", default=DEFAULT_TENANT, show_default=True, help="Tenant of the transaction."
)
@click.option("--json", "as_json", is_flag=True, help="Print the full status as JSON.")
@click.option("--events", "show_events", is_flag=True, help="List every event seen.")
@click.option(
    "--stall-after",
    type=float,
    metavar="SECONDS",
    help="Report an executing transaction with no event for this long as stalled.",
)
def status_cmd(
    correlation_id: str,
    storage_url: str,
    tenant: str,
    as_json: bool,
    show_events: bool,
    stall_after: float | None,
) -> None:
    """Show the aggregate status of the transaction CORRELATION_ID."""
    status = stalled_view(asyncio.run(_load(storage_url, correlation_id, tenant)), stall_after)
    if status is None:
        msg = f"No choreographed transaction '{correlation_id}' for tenant '{tenant}'"
        raise click.ClickException(msg)
    if as_json:
        click.echo(json.dumps(status.to_dict(), indent=2, sort_keys=True))
        return
    for line in _describe(status):
        click.echo(line)
    if show_events:
        for event in status.events:
            click.echo(f"    {event['at']}  {event['event_type']}  ({event.get('source') or '-'})")
