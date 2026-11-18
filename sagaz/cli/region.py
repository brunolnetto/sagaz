"""``sagaz region``: health and manual failover of regions (ADR-034, #59)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import click

from sagaz.core.regions import Region, RegionRegistry, bus_from_url, publish_failover
from sagaz.core.regions._config import regions_from_config
from sagaz.core.regions._protocol import HEARTBEAT

CONFIG_OPTION = click.option(
    "--config",
    "config_path",
    default="sagaz.yaml",
    show_default=True,
    type=click.Path(dir_okay=False),
    help="sagaz.yaml with a regions: block.",
)


def _load(config_path: str) -> tuple[list[Region], str]:
    import yaml

    from sagaz.core.env import get_env

    path = Path(config_path)
    if not path.exists():
        msg = f"Configuration file not found: {config_path}"
        raise click.ClickException(msg)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    env = get_env()
    env.load()
    block = env.substitute_dict(data).get("regions")
    if not block:
        msg = f"{config_path} has no regions: block"
        raise click.ClickException(msg)
    try:
        return regions_from_config(block), str(block.get("home", ""))
    except ValueError as error:
        raise click.ClickException(str(error)) from None


async def _connect(regions: list[Region]) -> tuple[dict[str, Any], dict[str, str]]:
    member = f"cli-{uuid4().hex[:8]}"
    buses, errors = {}, {}
    for region in regions:
        bus = bus_from_url(region.bus_url, f"sagaz-{member}", member)
        try:
            await bus.start()
            buses[region.name] = bus
        except Exception as error:
            errors[region.name] = str(error)
    return buses, errors


async def _listen(regions: list[Region], seconds: float) -> list[dict[str, Any]]:
    buses, errors = await _connect(regions)
    seen: dict[str, dict[str, float]] = {r.name: {} for r in regions}

    async def on_heartbeat(event) -> None:
        if event.data.get("region") in seen:
            seen[event.data["region"]][event.data.get("worker", "?")] = time.monotonic()

    for bus in buses.values():
        bus.subscribe(HEARTBEAT, on_heartbeat)
    await asyncio.sleep(seconds)
    for bus in buses.values():
        await bus.stop()
    rows = []
    for region in regions:
        workers = seen[region.name]
        status = "unreachable" if region.name in errors else ("up" if workers else "down")
        rows.append(
            {
                "region": region.name,
                "jurisdiction": region.jurisdiction,
                "priority": region.priority,
                "workers": len(workers),
                "status": status,
                "error": errors.get(region.name),
            }
        )
    return rows


@click.group("region")
def region_cli() -> None:
    """Inspect regions and fail them over (multi-region sagas)."""


@region_cli.command("list")
@CONFIG_OPTION
@click.option("--listen", default=3.0, show_default=True, help="Seconds to wait for heartbeats.")
@click.option("--json", "as_json", is_flag=True, help="Print JSON.")
def list_cmd(config_path: str, listen: float, as_json: bool) -> None:
    """Show each region and whether its workers are sending heartbeats."""
    regions, home = _load(config_path)
    rows = asyncio.run(_listen(regions, listen))
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    click.echo(f"{'REGION':<16}{'JURISDICTION':<14}{'PRIORITY':<10}{'WORKERS':<9}STATUS")
    for row in rows:
        name = row["region"] + (" *" if row["region"] == home else "")
        detail = f" ({row['error']})" if row["error"] else ""
        click.echo(
            f"{name:<16}{row['jurisdiction']:<14}{row['priority']:<10}"
            f"{row['workers']:<9}{row['status']}{detail}"
        )


async def _send_failover(
    regions: list[Region], source: str, target: str | None, force: bool
) -> tuple[int, dict[str, str]]:
    buses, errors = await _connect(regions)
    try:
        delivered = await publish_failover(buses, source, target, force)
    finally:
        for bus in buses.values():
            await bus.stop()
    return delivered, errors


@region_cli.command("failover")
@CONFIG_OPTION
@click.option("--from", "source", required=True, help="Region whose steps should move.")
@click.option("--to", "target", help="Region that runs them instead.")
@click.option("--restore", is_flag=True, help="Send the steps back to --from.")
@click.option("--force", is_flag=True, help="Allow a region of another jurisdiction.")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
def failover_cmd(
    config_path: str, source: str, target: str | None, restore: bool, force: bool, yes: bool
) -> None:
    """Route --from's steps to --to on every running coordinator (or --restore them)."""
    regions, home = _load(config_path)
    if restore == bool(target):
        msg = "Give either --to or --restore"
        raise click.ClickException(msg)
    registry = RegionRegistry(regions, home or regions[0].name)
    try:
        registry.get(source)
        if target:
            registry.failover(source, target, force=force)
    except ValueError as error:
        raise click.ClickException(str(error)) from None
    action = f"run {source}'s steps in {target}" if target else f"send steps back to {source}"
    if not yes:
        click.confirm(f"Tell every coordinator to {action}?", abort=True)
    delivered, errors = asyncio.run(_send_failover(regions, source, target, force))
    for name, problem in errors.items():
        click.echo(f"  ⚠ {name}: {problem}")
    if not delivered:
        msg = "No region bus accepted the command"
        raise click.ClickException(msg)
    click.echo(f"✓ Sent to {delivered} region bus(es): coordinators now {action}")
