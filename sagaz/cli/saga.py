"""``sagaz saga show <id>``: look a saga run up in storage (#538)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click

from sagaz.core.tenant import DEFAULT_TENANT, tenant_scope


@click.group(name="saga")
def saga_cli() -> None:
    """Look up saga runs stored by a saga storage."""


@saga_cli.command(name="show")
@click.argument("saga_id")
@click.option(
    "--storage-url",
    envvar="SAGAZ_STORAGE_URL",
    required=True,
    help="Saga storage URL, e.g. postgresql://..., sqlite:///sagas.db, redis://... "
    "(env: SAGAZ_STORAGE_URL)",
)
@click.option("--tenant", default=DEFAULT_TENANT, show_default=True, help="Tenant scope.")
@click.option("--json", "as_json", is_flag=True, help="Print the stored record as JSON.")
def show_cmd(saga_id: str, storage_url: str, tenant: str, as_json: bool) -> None:
    """Show a saga run: its status, each step's status and error, and its context."""
    record = asyncio.run(_load(storage_url, saga_id, tenant))
    if record is None:
        msg = f"no saga {saga_id!r} in {_redacted(storage_url)}"
        raise click.ClickException(msg)
    if as_json:
        click.echo(json.dumps(record, indent=2, default=str))
        return
    click.echo(_render(record))


async def _load(url: str, saga_id: str, tenant: str) -> dict[str, Any] | None:
    from sagaz.core.storage import create_storage_manager

    manager = create_storage_manager(url)
    await manager.initialize()
    try:
        with tenant_scope(tenant):
            return await manager.saga.load_saga_state(saga_id)
    finally:
        await manager.close()


def _render(record: dict[str, Any]) -> str:
    lines = [
        f"{'saga':<11}{record.get('saga_id')}  ({record.get('saga_name')})",
        f"{'status':<11}{record.get('status')}",
    ]
    lines += [
        f"{field.replace('_', ' '):<11}{record[field]}"
        for field in ("created_at", "updated_at")
        if record.get(field)
    ]
    lines += _step_lines(record.get("steps") or [])
    context = {
        k: v for k, v in (record.get("context") or {}).items() if not str(k).startswith("__")
    }
    if context:
        lines.append(f"{'context':<11}" + json.dumps(context, default=str))
    return "\n".join(lines)


def _step_lines(steps: list[dict[str, Any]]) -> list[str]:
    if not steps:
        return []
    width = max(len(str(step.get("name", ""))) for step in steps)
    return ["steps", *(_step_line(step, width) for step in steps)]


def _step_line(step: dict[str, Any], width: int) -> str:
    line = f"  {step.get('name', '')!s:<{width}}  {step.get('status', '')}"
    if step.get("retry_count"):
        line += f"  (retries: {step['retry_count']})"
    if step.get("error"):
        line += f"  error: {step['error']}"
    return line


def _redacted(url: str) -> str:
    """The URL without its password, for messages."""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.rsplit("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}" if ":" in credentials else url
