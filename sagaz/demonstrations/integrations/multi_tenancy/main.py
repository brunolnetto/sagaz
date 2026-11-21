#!/usr/bin/env python3
"""
Multi-tenancy — two tenants share one sagaz deployment, isolated end to end

Two tenants run the same order saga concurrently, with the same saga id:

  1. Setup   → a TenantRegistry with plans and quotas, one shared storage that
               encrypts each tenant's data with its own key
  2. Execute → acme's order completes, globex's payment is declined and the saga
               compensates; a third globex saga is refused by its concurrency quota
  3. Verify  → each tenant sees only its own saga, the default tenant sees
               neither, stored data is ciphertext, and per-tenant counts come from
               one system-scope pass (what metrics and dashboards would read)

Everything runs in-process (in-memory storage, keys from a dict standing in for
the environment); no external services are required.

Usage:
    sagaz demo run multi_tenancy
    python -m sagaz.demonstrations.integrations.multi_tenancy.main
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.exceptions import SagaFailedError
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.tenant import (
    QuotaExceededError,
    TenantContext,
    TenantQuotas,
    TenantRegistry,
    current_tenant_id,
    system_scope,
    tenant_scope,
)

try:  # encryption needs the optional ``cryptography`` package (sagaz[encryption])
    from sagaz.core.tenant.encryption import EncryptedSagaStorage, EnvKeyProvider, is_encrypted

    ENCRYPTION = True
except ImportError:  # pragma: no cover - only when cryptography is not installed
    ENCRYPTION = False

ORDER_ID = "order-1001"  # both tenants use the same saga id on purpose
CARD = "4111-1111-1111-1111"


class OrderSaga(Saga):
    """Reserve stock, then charge the card; a declined card releases the stock."""

    saga_name = "order"

    @action("reserve_stock")
    async def reserve_stock(self, ctx: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(ctx.get("hold", 0))  # lets the quota demo overlap sagas
        return {"reserved_by": current_tenant_id()}

    @compensate("reserve_stock")
    async def release_stock(self, ctx: dict[str, Any]) -> None:
        ctx["stock_released"] = True

    @action("charge_card", depends_on=["reserve_stock"])
    async def charge_card(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if ctx.get("declined"):
            msg = "card declined"
            raise RuntimeError(msg)
        return {"charged": ctx["amount"]}


@dataclass
class Deployment:
    """One sagaz deployment serving several tenants."""

    registry: TenantRegistry
    plain: InMemorySagaStorage  # what the database holds
    storage: Any  # what the application uses (encrypting when available)
    encrypted: bool = True
    outcomes: dict[str, str] = field(default_factory=dict)
    refused: list[str] = field(default_factory=list)

    def config(self) -> SagaConfig:
        return SagaConfig(
            storage=self.storage,  # type: ignore[arg-type]
            tenant_registry=self.registry,
            metrics=False,
            logging=False,
        )


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def setup(encryption: bool | None = None) -> Deployment:
    registry = TenantRegistry()
    registry.register(TenantContext("acme", plan="premium"))
    registry.register(
        TenantContext("globex", plan="standard", quotas=TenantQuotas(max_concurrent_sagas=2))
    )
    plain = InMemorySagaStorage()
    if not (ENCRYPTION if encryption is None else encryption):
        return Deployment(registry, plain, plain, encrypted=False)
    if not ENCRYPTION:
        msg = "encryption needs the cryptography package: pip install 'sagaz[encryption]'"
        raise ImportError(msg)
    keys = {"SAGAZ_TENANT_KEY_ACME": _key(), "SAGAZ_TENANT_KEY_GLOBEX": _key()}
    backend: Any = plain  # the in-memory backend predates the SagaStorage interface it satisfies
    return Deployment(registry, plain, EncryptedSagaStorage(backend, EnvKeyProvider(keys)))


async def _order(deployment: Deployment, tenant: str, saga_id: str, **ctx: Any) -> None:
    context = {"amount": 100, "card": CARD, **ctx}
    try:
        await OrderSaga(config=deployment.config()).run(
            context, saga_id=saga_id, tenant_context=tenant
        )
        deployment.outcomes[f"{tenant}/{saga_id}"] = "completed"
    except QuotaExceededError as exc:  # refused before the saga starts
        deployment.refused.append(f"{tenant}/{saga_id}: {exc}")
    except SagaFailedError:
        deployment.outcomes[f"{tenant}/{saga_id}"] = "rolled_back"


async def execute(deployment: Deployment) -> None:
    await asyncio.gather(
        _order(deployment, "acme", ORDER_ID),
        _order(deployment, "globex", ORDER_ID, declined=True),
    )
    # globex allows two concurrent sagas: the third one is refused.
    await asyncio.gather(*(_order(deployment, "globex", f"bulk-{i}", hold=0.02) for i in range(3)))


async def _visible(storage: Any, tenant: str | None) -> Any:
    if tenant is None:
        return await storage.load_saga_state(ORDER_ID)
    with tenant_scope(tenant):
        return await storage.load_saga_state(ORDER_ID)


async def per_tenant_counts(storage: Any) -> dict[str, Counter[str]]:
    """Sagas per tenant and status, from one system-scope listing."""
    counts: dict[str, Counter[str]] = {}
    with system_scope():
        for summary in await storage.list_sagas(limit=1000):
            counts.setdefault(summary["tenant_id"], Counter())[summary["status"]] += 1
    return counts


async def _visibility_problems(storage: Any) -> list[str]:
    problems: list[str] = []
    acme = await _visible(storage, "acme")
    globex = await _visible(storage, "globex")
    if not acme or acme["status"] != "completed" or acme["context"]["tenant_id"] != "acme":
        problems.append("acme does not see its own completed order")
    if not globex or globex["status"] != "rolled_back":
        problems.append("globex does not see its own rolled-back order")
    if await _visible(storage, None) is not None:
        problems.append("the default tenant can see a tenant's order")
    return problems


async def _encryption_problems(deployment: Deployment) -> list[str]:
    if not deployment.encrypted:
        return []
    raw = await _visible(deployment.plain, "acme")
    if raw is None or not is_encrypted(raw["context"]) or CARD in json.dumps(raw, default=str):
        return ["acme's order is stored in plaintext"]
    return []


async def _quota_and_count_problems(deployment: Deployment) -> list[str]:
    problems: list[str] = []
    if len(deployment.refused) != 1 or "max_concurrent_sagas" not in deployment.refused[0]:
        problems.append("globex's concurrency quota did not refuse exactly one saga")
    counts = await per_tenant_counts(deployment.plain)
    expected = {"acme": {"completed": 1}, "globex": {"rolled_back": 1, "completed": 2}}
    if {tenant: dict(c) for tenant, c in counts.items()} != expected:
        problems.append(f"unexpected per-tenant counts: {counts}")
    return problems


async def verify(deployment: Deployment) -> list[str]:
    """Return the violated isolation guarantees (empty when all hold)."""
    return [
        *await _visibility_problems(deployment.storage),
        *await _encryption_problems(deployment),
        *await _quota_and_count_problems(deployment),
    ]


def _report(deployment: Deployment, counts: dict[str, Counter[str]]) -> None:
    for name, outcome in sorted(deployment.outcomes.items()):
        print(f"  ▶ {name:<20} {outcome}")
    for refusal in deployment.refused:
        print(f"  ⛔ {refusal}")
    print("\n  Per-tenant sagas (system scope):")
    for tenant, by_status in sorted(counts.items()):
        print(f"    {tenant:<8} {dict(sorted(by_status.items()))}")


async def _run() -> None:
    # Phase 1: Setup
    deployment = setup()
    plans = ", ".join(f"{t.tenant_id} ({t.plan})" for t in deployment.registry.list())
    keys = (
        "each tenant's data encrypted with its key"
        if deployment.encrypted
        else "no encryption (install sagaz[encryption] to enable it)"
    )
    print(f"👥 One deployment, tenants: {plans}; {keys}\n")

    # Phase 2: Execute
    await execute(deployment)
    _report(deployment, await per_tenant_counts(deployment.plain))

    # Phase 3: Verify
    problems = await verify(deployment)
    print()
    if problems:
        for problem in problems:
            print(f"❌ {problem}")
        msg = "tenant isolation did not hold"
        raise RuntimeError(msg)
    encrypted = ", data encrypted" if deployment.encrypted else ""
    print(f"✅ Same saga id, two tenants: no data crossed, quotas enforced{encrypted}")


if __name__ == "__main__":
    asyncio.run(_run())
