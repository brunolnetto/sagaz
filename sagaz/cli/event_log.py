"""``sagaz event-log``: a saga's event stream as a timeline (ADR-033, #57)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click

from sagaz.core.events import SagaEvent
from sagaz.core.tenant import DEFAULT_TENANT, tenant_scope


async def _load(url: str, saga_id: str, tenant: str) -> tuple[list[SagaEvent], Any]:
    from sagaz.core.storage.event_store import create_event_store
    from sagaz.projections import load_projection

    async with create_event_store(url) as store:
        with tenant_scope(tenant):
            return await store.load_stream(saga_id), await load_projection(store, saga_id)


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
def event_log_cmd(saga_id: str, store_url: str, tenant: str, as_json: bool) -> None:
    """Show every recorded event of the event-sourced saga SAGA_ID."""
    events, state = asyncio.run(_load(store_url, saga_id, tenant))
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
