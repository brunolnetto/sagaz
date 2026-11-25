"""``SagaOrchestrator`` runs and tracks ``sagaz.Saga`` (#544)."""

from __future__ import annotations

import logging

import pytest

from sagaz import Saga, SagaAlreadyExistsError, SagaFailedError, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.execution.orchestrator import SagaOrchestrator
from sagaz.core.saga import Saga as ClassicSaga
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.tenant import TenantContext, TenantQuotas, current_tenant_id
from sagaz.core.types import SagaStatus


def config(storage=None) -> SagaConfig:
    return SagaConfig(metrics=False, logging=False, storage=storage, default_max_retries=0)


class Order(Saga):
    saga_name = "order"

    @action("reserve")
    async def reserve(self, ctx):
        return {"reserved": True, "tenant_seen": current_tenant_id()}

    @compensate("reserve")
    async def release(self, ctx):
        if ctx.get("release_fails"):
            msg = "warehouse offline"
            raise RuntimeError(msg)

    @action("charge", depends_on=["reserve"])
    async def charge(self, ctx):
        if ctx.get("decline"):
            msg = "card declined"
            raise RuntimeError(msg)
        return {"charged": True}


class TestRun:
    async def test_it_returns_the_final_context_and_tracks_the_run(self):
        orchestrator = SagaOrchestrator()
        saga = Order(config=config())
        context = await orchestrator.run(saga, {"order_id": "o-1"}, saga_id="s-1")
        assert context["charged"] is True
        assert await orchestrator.get_saga("s-1") is saga
        assert await orchestrator.get_saga_status("s-1") == {
            "saga_id": "s-1",
            "name": "order",
            "status": "completed",
            "error": None,
        }

    async def test_a_saga_id_is_generated_so_the_run_can_be_looked_up(self):
        orchestrator = SagaOrchestrator()
        context = await orchestrator.run(Order(config=config()), {})
        assert (await orchestrator.get_saga_status(context["saga_id"]))["status"] == "completed"

    async def test_a_rolled_back_saga_raises_and_is_tracked_as_rolled_back(self):
        orchestrator = SagaOrchestrator()
        with pytest.raises(SagaFailedError):
            await orchestrator.run(Order(config=config()), {"decline": True}, saga_id="s-1")
        status = await orchestrator.get_saga_status("s-1")
        assert status["status"] == "rolled_back"
        assert "card declined" in status["error"]

    async def test_a_failed_compensation_is_tracked_as_failed(self):
        orchestrator = SagaOrchestrator()
        failing = {"decline": True, "release_fails": True}
        cfg = SagaConfig(metrics=False, logging=False, default_max_retries=0)
        saga = Order(config=cfg)
        saga.get_step("reserve").compensation_max_retries = 0
        with pytest.raises(SagaFailedError):
            await orchestrator.run(saga, failing, saga_id="s-1")
        assert (await orchestrator.get_saga_status("s-1"))["status"] == "failed"

    async def test_a_run_refused_before_any_step_is_tracked_as_failed(self):
        storage = InMemorySagaStorage()
        orchestrator = SagaOrchestrator()
        await orchestrator.run(Order(config=config(storage)), {}, saga_id="s-1")
        with pytest.raises(SagaAlreadyExistsError):
            await orchestrator.run(Order(config=config(storage)), {}, saga_id="s-1")
        await orchestrator.run(Order(config=config(storage)), {}, saga_id="s-1", allow_rerun=True)
        assert (await orchestrator.get_saga_status("s-1"))["status"] == "completed"

    async def test_the_orchestrators_tenant_is_the_sagas(self):
        acme = TenantContext("acme", quotas=TenantQuotas(max_concurrent_sagas=5))
        orchestrator = SagaOrchestrator(tenant=acme)
        context = await orchestrator.run(Order(config=config()), {})
        assert context["tenant_seen"] == "acme"
        assert context["tenant_id"] == "acme"

    async def test_verbose_logs_the_outcome(self, caplog):
        orchestrator = SagaOrchestrator(verbose=True)
        with caplog.at_level(logging.INFO):
            await orchestrator.run(Order(config=config()), {}, saga_id="s-1")
        assert "Saga order [s-1] finished with status: completed" in caplog.text


class TestBothKinds:
    async def test_statistics_and_counts_cover_classic_and_sagaz_sagas(self):
        orchestrator = SagaOrchestrator()
        await orchestrator.run(Order(config=config()), {}, saga_id="new-ok")
        with pytest.raises(SagaFailedError):
            await orchestrator.run(Order(config=config()), {"decline": True}, saga_id="new-bad")

        async def step(ctx):
            return "done"

        classic = ClassicSaga("classic")
        await classic.add_step("a", step)
        await orchestrator.execute_saga(classic)

        stats = await orchestrator.get_statistics()
        assert stats["total_sagas"] == 3
        assert stats["completed"] == 2
        assert stats["rolled_back"] == 1
        assert await orchestrator.count_completed() == 2
        assert await orchestrator.count_rolled_back() == 1
        assert await orchestrator.count_by_status(SagaStatus.FAILED) == 0
        statuses = {s["status"] for s in await orchestrator.get_all_sagas_status()}
        assert statuses == {"completed", "rolled_back"}
        assert (await orchestrator.get_saga_status(classic.saga_id))["status"] == "completed"

    async def test_an_unknown_saga_has_no_status(self):
        assert await SagaOrchestrator().get_saga_status("nope") is None


async def test_the_orchestrator_passes_a_deadline_on():
    import asyncio

    from sagaz import SagaTimeoutError

    class Slow(Saga):
        saga_name = "slow"

        @action("wait")
        async def wait(self, ctx):
            await asyncio.sleep(5)

    orchestrator = SagaOrchestrator()
    with pytest.raises(SagaFailedError) as raised:
        await orchestrator.run(Slow(config=config()), {}, saga_id="s-1", deadline=0.05)
    assert isinstance(raised.value.__cause__, SagaTimeoutError)
    assert (await orchestrator.get_saga_status("s-1"))["status"] == "rolled_back"
