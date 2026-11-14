"""``sagaz tenant``: manage tenants and their quotas (ADR-020).

Tenants are persisted in the saga storage given by ``--storage-url`` (or
``SAGAZ_STORAGE_URL``), the same storage the application's ``TenantRegistry``
loads from.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import click

from sagaz.core.tenant import (
    TenantContext,
    TenantError,
    TenantQuotas,
    TenantRegistry,
    validate_tenant_id,
)

T = TypeVar("T")

STORAGE_URL = click.option(
    "--storage-url",
    envvar="SAGAZ_STORAGE_URL",
    required=True,
    metavar="URL",
    help="Saga storage holding the tenant registry (env: SAGAZ_STORAGE_URL).",
)


def _quota_options(fn: Callable[..., Any]) -> Callable[..., Any]:
    options = [
        click.option("--max-concurrent-sagas", type=click.IntRange(min=0), default=None),
        click.option(
            "--max-step-duration",
            "max_step_duration_seconds",
            type=click.FloatRange(min=0),
            default=None,
            help="Seconds.",
        ),
        click.option("--max-retries", type=click.IntRange(min=0), default=None),
    ]
    for option in reversed(options):
        fn = option(fn)
    return fn


def _with_registry(storage_url: str, work: Callable[[TenantRegistry], Awaitable[T]]) -> T:
    """Load the registry from storage, run ``work`` and translate tenant errors."""
    from sagaz.core.storage import create_storage_manager

    async def run() -> T:
        async with create_storage_manager(url=storage_url) as manager:
            registry = await TenantRegistry.from_storage(manager.saga)
            return await work(registry)

    try:
        return asyncio.run(run())
    except (TenantError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


def _quota_text(quotas: TenantQuotas) -> str:
    limits = {k: v for k, v in quotas.to_dict().items() if v is not None}
    return ", ".join(f"{k}={v:g}" for k, v in limits.items()) or "unlimited"


def _describe(tenant: TenantContext) -> str:
    status = "active" if tenant.active else "suspended"
    return f"{tenant.tenant_id}  plan={tenant.plan}  {status}  quotas: {_quota_text(tenant.quotas)}"


@click.group("tenant")
def tenant_cli() -> None:
    """Manage tenants and their quotas (multi-tenancy, ADR-020)."""


@tenant_cli.command("list")
@STORAGE_URL
def list_tenants(storage_url: str) -> None:
    """List registered tenants."""

    async def work(registry: TenantRegistry) -> list[TenantContext]:
        return registry.list()

    tenants = _with_registry(storage_url, work)
    if not tenants:
        click.echo("No tenants registered.")
    for tenant in tenants:
        click.echo(_describe(tenant))


@tenant_cli.command("create")
@click.argument("tenant_id")
@click.option("--plan", default="standard", show_default=True)
@click.option("--name", default=None, help="Display name.")
@_quota_options
@STORAGE_URL
def create_tenant(
    tenant_id: str, plan: str, name: str | None, storage_url: str, **quotas: Any
) -> None:
    """Register TENANT_ID (lowercase letters, digits, '-', '_', '.')."""
    try:
        validate_tenant_id(tenant_id)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="TENANT_ID") from exc

    async def work(registry: TenantRegistry) -> TenantContext:
        tenant = registry.register(
            TenantContext(tenant_id, plan=plan, name=name, quotas=TenantQuotas(**quotas))
        )
        await registry.save()
        return tenant

    click.echo(f"Created {_describe(_with_registry(storage_url, work))}")


@tenant_cli.command("delete")
@click.argument("tenant_id")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation.")
@STORAGE_URL
def delete_tenant(tenant_id: str, yes: bool, storage_url: str) -> None:
    """Remove TENANT_ID from the registry (its saga data is not deleted)."""
    if not yes:
        click.confirm(f"Delete tenant '{tenant_id}'?", abort=True)

    async def work(registry: TenantRegistry) -> TenantContext:
        tenant = registry.delete(tenant_id)
        await registry.save()
        return tenant

    _with_registry(storage_url, work)
    click.echo(f"Deleted tenant '{tenant_id}'.")


@tenant_cli.command("quota")
@click.argument("tenant_id")
@_quota_options
@click.option("--clear", is_flag=True, help="Remove every quota (unlimited).")
@STORAGE_URL
def tenant_quota(tenant_id: str, clear: bool, storage_url: str, **quotas: Any) -> None:
    """Show TENANT_ID's quotas, or change the ones given as options."""
    changes = {k: v for k, v in quotas.items() if v is not None}

    async def work(registry: TenantRegistry) -> TenantContext:
        tenant = registry.get(tenant_id)
        if not (changes or clear):
            return tenant
        base = {} if clear else tenant.quotas.to_dict()
        tenant = registry.set_quotas(tenant_id, TenantQuotas(**{**base, **changes}))
        await registry.save()
        return tenant

    click.echo(_describe(_with_registry(storage_url, work)))


def _set_active(tenant_id: str, active: bool, storage_url: str) -> None:
    async def work(registry: TenantRegistry) -> TenantContext:
        tenant = registry.set_active(tenant_id, active)
        await registry.save()
        return tenant

    click.echo(_describe(_with_registry(storage_url, work)))


@tenant_cli.command("suspend")
@click.argument("tenant_id")
@STORAGE_URL
def suspend_tenant(tenant_id: str, storage_url: str) -> None:
    """Stop TENANT_ID from running sagas."""
    _set_active(tenant_id, False, storage_url)


@tenant_cli.command("activate")
@click.argument("tenant_id")
@STORAGE_URL
def activate_tenant(tenant_id: str, storage_url: str) -> None:
    """Allow a suspended TENANT_ID to run sagas again."""
    _set_active(tenant_id, True, storage_url)
