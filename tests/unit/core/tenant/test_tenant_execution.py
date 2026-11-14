"""Running sagas as a tenant: scope, context, registry and quotas (ADR-020, #54)."""

from __future__ import annotations

import asyncio

import pytest

from sagaz import Saga, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.execution.orchestrator import SagaOrchestrator
from sagaz.core.saga import Saga as ImperativeSaga
from sagaz.core.tenant import (
    CrossTenantAccessError,
    QuotaExceededError,
    TenantContext,
    TenantNotFoundError,
    TenantQuotas,
    TenantRegistry,
    TenantSuspendedError,
    current_tenant_id,
    quota_enforcer,
)
from sagaz.core.types import SagaStatus

SEEN: list[str] = []


class ProbeSaga(Saga):
    saga_name = "probe"

    @action("observe")
    async def observe(self, ctx):
        SEEN.append(current_tenant_id())
        return {"seen": current_tenant_id()}


class SlowSaga(Saga):
    saga_name = "slow"

    @action("wait", timeout_seconds=30.0)
    async def wait(self, ctx):
        await asyncio.sleep(ctx.get("sleep", 0.5))
        return {"done": True}

    @compensate("wait")
    async def undo(self, ctx):
        return None


@pytest.fixture(autouse=True)
def _reset():
    SEEN.clear()
    yield
    assert quota_enforcer._running == {}, "a test leaked a concurrency slot"


class TestSagaRunAsTenant:
    async def test_steps_run_in_the_tenant_scope_and_context_names_it(self):
        result = await ProbeSaga().run({"order": 1}, tenant_context=TenantContext("acme"))
        assert SEEN == ["acme"]
        assert result["tenant_id"] == "acme"
        assert current_tenant_id() == "default"

    async def test_without_tenant_nothing_changes(self):
        result = await ProbeSaga().run({"order": 1})
        assert SEEN == ["default"]
        assert "tenant_id" not in result

    async def test_tenant_id_string_without_registry(self):
        result = await ProbeSaga().run({}, tenant_context="beta")
        assert result["tenant_id"] == "beta"

    async def test_tenant_id_is_resolved_through_the_configured_registry(self):
        registry = TenantRegistry()
        registry.register(
            TenantContext("acme", quotas=TenantQuotas(max_step_duration_seconds=0.05))
        )
        saga = SlowSaga(config=SagaConfig(tenant_registry=registry))
        with pytest.raises(TimeoutError, match="timed out after 0.05s"):
            await saga.run({"sleep": 0.5}, tenant_context="acme")

    async def test_unknown_tenant_with_a_registry_is_rejected(self):
        saga = ProbeSaga(config=SagaConfig(tenant_registry=TenantRegistry()))
        with pytest.raises(TenantNotFoundError):
            await saga.run({}, tenant_context="ghost")
        assert SEEN == []

    async def test_context_claiming_another_tenant_is_rejected(self):
        with pytest.raises(CrossTenantAccessError):
            await ProbeSaga().run({"tenant_id": "beta"}, tenant_context="acme")
        assert SEEN == []

    async def test_matching_context_tenant_is_accepted(self):
        result = await ProbeSaga().run({"tenant_id": "acme"}, tenant_context="acme")
        assert result["tenant_id"] == "acme"

    async def test_suspended_tenant_cannot_run(self):
        with pytest.raises(TenantSuspendedError):
            await ProbeSaga().run({}, tenant_context=TenantContext("acme", active=False))
        assert SEEN == []


class TestQuotasDuringExecution:
    async def test_concurrent_sagas_beyond_the_quota_are_refused(self):
        tenant = TenantContext("acme", quotas=TenantQuotas(max_concurrent_sagas=1))
        first = asyncio.create_task(SlowSaga().run({"sleep": 0.2}, tenant_context=tenant))
        await asyncio.sleep(0.05)
        with pytest.raises(QuotaExceededError, match="max_concurrent_sagas"):
            await SlowSaga().run({"sleep": 0}, tenant_context=tenant)
        await first
        await SlowSaga().run({"sleep": 0}, tenant_context=tenant)  # slot released

    async def test_other_tenants_are_not_limited_by_it(self):
        acme = TenantContext("acme", quotas=TenantQuotas(max_concurrent_sagas=1))
        first = asyncio.create_task(SlowSaga().run({"sleep": 0.2}, tenant_context=acme))
        await asyncio.sleep(0.05)
        await SlowSaga().run({"sleep": 0}, tenant_context="beta")
        await first

    async def test_step_duration_quota_lowers_the_timeout(self):
        tenant = TenantContext("acme", quotas=TenantQuotas(max_step_duration_seconds=0.05))
        with pytest.raises(TimeoutError, match="0.05s"):
            await SlowSaga().run({"sleep": 0.5}, tenant_context=tenant)

    async def test_retry_quota_caps_imperative_step_attempts(self):
        attempts = {"n": 0}

        async def flaky(ctx):
            attempts["n"] += 1
            msg = "boom"
            raise RuntimeError(msg)

        saga = ImperativeSaga("flaky", retry_backoff_base=0.001)
        await saga.add_step("charge", flaky, max_retries=5)
        tenant = TenantContext("acme", quotas=TenantQuotas(max_retries=1))

        result = await SagaOrchestrator(tenant_id=tenant).execute_saga(saga)

        assert not result.success
        assert result.status == SagaStatus.ROLLED_BACK
        assert attempts["n"] == 2  # initial attempt + 1 retry instead of 5

    async def test_imperative_timeout_quota(self):
        async def slow(ctx):
            await asyncio.sleep(0.5)

        saga = ImperativeSaga("slow-imperative", retry_backoff_base=0.001)
        await saga.add_step("wait", slow, timeout=30.0, max_retries=0)
        tenant = TenantContext("acme", quotas=TenantQuotas(max_step_duration_seconds=0.05))

        started = asyncio.get_running_loop().time()
        result = await SagaOrchestrator(tenant_id=tenant).execute_saga(saga)

        assert not result.success
        assert asyncio.get_running_loop().time() - started < 0.4  # 0.05s cap, not 30s


class TestOrchestrator:
    async def test_sagas_run_in_the_orchestrator_tenant(self):
        async def observe(ctx):
            SEEN.append(current_tenant_id())

        saga = ImperativeSaga("observe")
        await saga.add_step("observe", observe)

        result = await SagaOrchestrator(tenant_id="acme").execute_saga(saga)

        assert result.success
        assert SEEN == ["acme"]

    async def test_tenant_ids_are_resolved_through_the_registry(self):
        registry = TenantRegistry()
        registry.register(TenantContext("acme", plan="premium"))
        orchestrator = SagaOrchestrator(tenant_id="acme", tenant_registry=registry)
        assert orchestrator.tenant.plan == "premium"
        with pytest.raises(TenantNotFoundError):
            SagaOrchestrator(tenant_id="ghost", tenant_registry=registry)

    async def test_without_tenant_the_orchestrator_is_unchanged(self):
        async def observe(ctx):
            SEEN.append(current_tenant_id())

        saga = ImperativeSaga("observe")
        await saga.add_step("observe", observe)
        orchestrator = SagaOrchestrator()

        await orchestrator.execute_saga(saga)

        assert orchestrator.tenant is None
        assert SEEN == ["default"]


async def test_retry_quota_caps_imperative_compensation_attempts():
    attempts = {"n": 0}

    async def reserve(ctx):
        return {"reserved": True}

    async def release(result, ctx):
        attempts["n"] += 1
        msg = "still down"
        raise RuntimeError(msg)

    async def charge(ctx):
        msg = "declined"
        raise RuntimeError(msg)

    saga = ImperativeSaga("compensating", retry_backoff_base=0.001)
    await saga.add_step("reserve", reserve, release, max_retries=0)
    await saga.add_step("charge", charge, max_retries=0)
    tenant = TenantContext("acme", quotas=TenantQuotas(max_retries=0))

    await SagaOrchestrator(tenant_id=tenant).execute_saga(saga)

    assert attempts["n"] == 1  # 3 attempts by default, 1 with max_retries=0
