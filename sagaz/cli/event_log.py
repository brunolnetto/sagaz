"""``sagaz event-log``: a saga's event stream as a timeline (ADR-033, #57)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import Any

import click

from sagaz.core.events import SagaEvent
from sagaz.core.tenant import DEFAULT_TENANT, tenant_scope


def _store(url: str, layout: str) -> Any:
    if layout == "unified":  # ADR-041: the event store is a view on the saga log
        from sagaz.core.storage.saga_log import create_saga_log_store
        from sagaz.core.storage.saga_log.event_store import SagaLogEventStore

        return SagaLogEventStore(create_saga_log_store(url))
    from sagaz.core.storage.event_store import create_event_store

    return create_event_store(url)


async def _load(
    url: str, saga_id: str, tenant: str, layout: str = "classic"
) -> tuple[list[SagaEvent], Any]:
    from sagaz.projections import load_projection

    async with _store(url, layout) as store:
        with tenant_scope(tenant):
            return await store.load_stream(saga_id), await load_projection(store, saga_id)


async def _load_choreographed(url: str, saga_id: str, tenant: str) -> tuple[Any, list] | None:
    """A choreographed transaction and its events, or None for an orchestrated saga (#557).

    The event store view on the log reads orchestrated lifecycle events; a
    choreography's business events are read from the log directly.
    """
    from sagaz.core.storage.saga_log import create_saga_log_store
    from sagaz.core.storage.saga_log._model import Coordination

    async with create_saga_log_store(url) as log:
        with tenant_scope(tenant):
            transaction = await log.get_transaction(saga_id)
            if transaction is None or transaction.coordination != Coordination.CHOREOGRAPHED:
                return None
            return transaction, await log.events(saga_id)


def _show_choreographed(transaction: Any, events: list, as_json: bool) -> None:
    if as_json:
        document = {
            "transaction": dataclasses.asdict(transaction),
            "events": [dataclasses.asdict(event) for event in events],
        }
        click.echo(json.dumps(document, indent=2, sort_keys=True, default=str))
        return
    click.echo(
        f"Transaction {transaction.transaction_id} (choreographed flow {transaction.flow}, "
        f"tenant {transaction.tenant_id}): {transaction.status}"
    )
    for event in events:
        when = event.occurred_at.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        source = event.source or "?"
        click.echo(f"  {event.sequence:>4}  {when}  {source:<18}  {event.event_type}".rstrip())


def _details(event: SagaEvent) -> str:
    payload = event.payload
    step = payload.get("step_name") or payload.get("failed_step")
    error = payload.get("error_message")
    parts = [step] if step else []
    if error:
        parts.append(f"{payload.get('error_type') or 'error'}: {error}")
    if "duration_ms" in payload:
        parts.append(f"{payload['duration_ms']:.1f} ms")
    return "  ".join(parts)


@click.command("event-log")
@click.argument("saga_id")
@click.option(
    "--store-url",
    envvar="SAGAZ_EVENT_STORE_URL",
    required=True,
    metavar="URL",
    help="Event store: postgresql://..., sqlite://<path> (env: SAGAZ_EVENT_STORE_URL).",
)
@click.option("--tenant", default=DEFAULT_TENANT, show_default=True, help="Tenant of the saga.")
@click.option("--json", "as_json", is_flag=True, help="Print the events and state as JSON.")
@click.option(
    "--layout",
    type=click.Choice(["classic", "unified", "legacy"]),
    default="classic",
    show_default=True,
    help="Read the ADR-033 event store (classic; 'legacy' is its former name) or the "
    "unified saga log (ADR-041).",
)
def event_log_cmd(saga_id: str, store_url: str, tenant: str, as_json: bool, layout: str) -> None:
    """Show every recorded event of the saga or choreographed transaction SAGA_ID."""
    if layout == "unified":
        choreographed = asyncio.run(_load_choreographed(store_url, saga_id, tenant))
        if choreographed is not None:
            _show_choreographed(*choreographed, as_json)
            return
    events, state = asyncio.run(_load(store_url, saga_id, tenant, layout))
    if not events:
        msg = f"No events for saga '{saga_id}' (tenant '{tenant}')"
        raise click.ClickException(msg)
    if as_json:
        document = {"events": [e.to_dict() for e in events], "state": state.to_dict()}
        click.echo(json.dumps(document, indent=2, sort_keys=True))
        return
    click.echo(
        f"Saga {saga_id} ({state.saga_name or '?'}, tenant {state.tenant_id}): {state.status}"
    )
    for event in events:
        when = event.occurred_at.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        click.echo(
            f"  {event.sequence:>4}  {when}  {event.event_type:<22}  {_details(event)}".rstrip()
        )
