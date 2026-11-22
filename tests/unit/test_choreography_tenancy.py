"""Choreography resolves, refuses and limits tenants as orchestration does (#564)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from sagaz.choreography import ChoreographedSaga, ChoreographyEngine, Event, EventBus
from sagaz.choreography.events import COMPENSATE
from sagaz.core.tenant import (
    QuotaExceededError,
    TenantContext,
    TenantNotFoundError,
    TenantQuotas,
    TenantRegistry,
    TenantSuspendedError,
    quota_enforcer,
)


def tenant_id() -> str:
    return f"t{uuid4().hex[:12]}"  # the quota slots are process-wide: one tenant per test


def registry_with(*tenants: TenantContext) -> TenantRegistry:
    registry = TenantRegistry()
    for tenant in tenants:
        registry.register(tenant)
    return registry


class Shop:
    """orders -> inventory (order.created, compensable) -> payments (stock.reserved)."""

    def __init__(self, registry: TenantRegistry | None, *, pay_fails: bool = False) -> None:
        self.bus = EventBus()
        self.engine = ChoreographyEngine(self.bus, tenant_registry=registry, retry_backoff_base=0)
        self.reserved: list[str] = []
        self.released: list[str] = []
        self.paid: list[str] = []
        self.compensations: list[Event] = []
        self.pay_attempts = 0

        async def reserve(event: Event, me: ChoreographedSaga) -> None:
            self.reserved.append(event.saga_id or "")
            await me.emit("stock.reserved")

        async def release(event: Event, me: ChoreographedSaga) -> None:
            self.released.append(event.saga_id or "")

        async def pay(event: Event, me: ChoreographedSaga) -> None:
            self.pay_attempts += 1
            if pay_fails:
                msg = "card declined"
                raise RuntimeError(msg)
            self.paid.append(event.saga_id or "")

        self.orders = ChoreographedSaga(name="orders")
        self.engine.register(self.orders)
        self.engine.register(
            ChoreographedSaga(name="inventory").on("order.created", reserve, release)
        )
        self.engine.register(ChoreographedSaga(name="payments").on("stock.reserved", pay))
        self.bus.subscribe(COMPENSATE, self.compensations.append)

    async def __aenter__(self) -> Shop:
        await self.engine.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.engine.stop()


class TestBegin:
    async def test_an_unknown_tenant_is_refused_before_publishing(self):
        async with Shop(registry_with()) as shop:
            with pytest.raises(TenantNotFoundError):
                await shop.orders.begin("order.created", tenant=tenant_id(), correlation_id="o-1")
            assert shop.bus.published == []

    async def test_a_suspended_tenant_is_refused_and_its_id_is_not_spent(self):
        acme = TenantContext(tenant_id(), active=False)
        registry = registry_with(acme)
        async with Shop(registry) as shop:
            with pytest.raises(TenantSuspendedError):
                await shop.orders.begin(
                    "order.created", tenant=acme.tenant_id, correlation_id="o-1"
                )
            registry.set_active(acme.tenant_id, True)
            await shop.orders.begin("order.created", tenant=acme.tenant_id, correlation_id="o-1")
            assert shop.paid == ["o-1"]  # the refused begin did not claim the id (#562)

    async def test_over_the_quota_begin_raises_and_the_slot_is_shared_with_orchestration(self):
        acme = TenantContext(tenant_id(), quotas=TenantQuotas(max_concurrent_sagas=1))
        async with Shop(registry_with(acme)) as shop:
            quota_enforcer.acquire(acme)  # an orchestrated saga of acme is running
            try:
                with pytest.raises(QuotaExceededError):
                    await shop.orders.begin("order.created", tenant=acme.tenant_id)
                assert shop.bus.published == []
            finally:
                quota_enforcer.release(acme.tenant_id)
            await shop.orders.begin("order.created", tenant=acme.tenant_id, correlation_id="o-2")
            assert shop.paid == ["o-2"]
            assert quota_enforcer.running(acme.tenant_id) == 0  # released afterwards


class TestDeliveries:
    async def test_an_unknown_tenant_is_refused_and_compensated(self):
        async with Shop(registry_with()) as shop:
            await shop.bus.publish(Event("order.created", saga_id="o-1", tenant_id=tenant_id()))
            assert shop.reserved == []  # the handler did not run
            assert len(shop.compensations) == 1
            report = shop.compensations[0].data
            assert report["participant"] == "inventory"
            assert "TenantNotFoundError" in report["reason"]

    async def test_a_suspended_tenant_is_refused_and_compensated(self):
        acme = TenantContext(tenant_id(), active=False)
        async with Shop(registry_with(acme)) as shop:
            await shop.bus.publish(Event("order.created", saga_id="o-1", tenant_id=acme.tenant_id))
            assert shop.reserved == []
            assert "TenantSuspendedError" in shop.compensations[0].data["reason"]

    async def test_a_redelivered_refused_event_is_not_compensated_twice(self):
        async with Shop(registry_with()) as shop:
            event = Event("order.created", saga_id="o-1", tenant_id=tenant_id())
            await shop.bus.publish(event)
            await shop.bus.publish(event)
            assert len(shop.compensations) == 1

    async def test_compensation_runs_for_a_tenant_suspended_meanwhile(self):
        acme = TenantContext(tenant_id())
        registry = registry_with(acme)
        async with Shop(registry, pay_fails=True) as shop:
            registry_suspends = registry.set_active

            async def suspend_then_fail(event: Event, me: ChoreographedSaga) -> None:
                registry_suspends(acme.tenant_id, False)
                msg = "card declined"
                raise RuntimeError(msg)

            shop.engine.register(
                ChoreographedSaga(name="payments").on("stock.reserved", suspend_then_fail)
            )
            await shop.orders.begin("order.created", tenant=acme.tenant_id, correlation_id="o-1")
            assert shop.reserved == ["o-1"]
            assert shop.released == ["o-1"]  # undone although acme is now suspended

    async def test_a_delivery_over_the_quota_waits_for_a_slot(self):
        acme = TenantContext(tenant_id(), quotas=TenantQuotas(max_concurrent_sagas=1))
        async with Shop(registry_with(acme)) as shop:
            quota_enforcer.acquire(acme)  # another transaction of acme holds the slot
            delivery = asyncio.create_task(
                shop.bus.publish(Event("order.created", saga_id="o-1", tenant_id=acme.tenant_id))
            )
            await asyncio.sleep(0.05)
            assert shop.reserved == []  # waiting, not refused
            assert shop.compensations == []
            quota_enforcer.release(acme.tenant_id)
            await asyncio.wait_for(delivery, 5)
            assert shop.reserved == ["o-1"]
            assert shop.paid == ["o-1"]

    async def test_one_transaction_takes_one_slot_however_many_nested_handlers(self):
        acme = TenantContext(tenant_id(), quotas=TenantQuotas(max_concurrent_sagas=1))
        async with Shop(registry_with(acme)) as shop:
            begin = shop.orders.begin("order.created", tenant=acme.tenant_id, correlation_id="o-1")
            await asyncio.wait_for(begin, 5)  # inventory and payments nest in-process
            assert shop.paid == ["o-1"]
            assert quota_enforcer.running(acme.tenant_id) == 0


class TestCaps:
    async def test_the_tenants_max_retries_caps_a_handlers(self):
        acme = TenantContext(tenant_id(), quotas=TenantQuotas(max_retries=0))
        async with Shop(registry_with(acme), pay_fails=True) as shop:  # engine default: 3 retries
            await shop.orders.begin("order.created", tenant=acme.tenant_id, correlation_id="o-1")
            assert shop.pay_attempts == 1
            assert shop.released == ["o-1"]

    async def test_the_tenants_step_duration_caps_a_handlers_timeout(self):
        acme = TenantContext(
            tenant_id(), quotas=TenantQuotas(max_step_duration_seconds=0.01, max_retries=0)
        )
        async with Shop(registry_with(acme)) as shop:

            async def slow(event: Event, me: ChoreographedSaga) -> None:
                await asyncio.sleep(5)

            shop.engine.register(ChoreographedSaga(name="payments").on("stock.reserved", slow))
            await asyncio.wait_for(
                shop.orders.begin("order.created", tenant=acme.tenant_id, correlation_id="o-1"), 3
            )
            assert "TimeoutError" in shop.compensations[0].data["reason"]


async def test_without_a_registry_an_event_runs_for_the_tenant_it_names():
    async with Shop(None) as shop:
        await shop.bus.publish(Event("order.created", saga_id="o-1", tenant_id=tenant_id()))
        assert shop.paid == ["o-1"]
        assert shop.compensations == []
