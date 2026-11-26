"""A step with an idempotency key runs once per tenant, across sagas (#569)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from sagaz import Saga, StepInDoubtError, action, compensate, release_step_key
from sagaz.core.config import SagaConfig
from sagaz.core.decorators._idempotency import STEP_KEY_RECORD_NAME, record_id, render_key
from sagaz.core.exceptions import SagaDefinitionError, SagaFailedError
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
from sagaz.core.tenant import tenant_scope


def config(storage) -> SagaConfig:
    return SagaConfig(metrics=False, logging=False, storage=storage, default_max_retries=0)


@pytest.fixture(params=["memory", "sqlite"])
async def storage(request, tmp_path):
    if request.param == "memory":
        yield InMemorySagaStorage()
        return
    store = SQLiteSagaStorage(str(tmp_path / "sagas.db"))
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


def checkout(calls: list[str], *, ship_fails: bool = False, charge_fails: bool = False):
    class Checkout(Saga):
        saga_name = "checkout"

        @action("charge", idempotency_key="charge-{order_id}")
        async def charge(self, ctx):
            calls.append("charge")
            if charge_fails:
                msg = "gateway down"
                raise RuntimeError(msg)
            return {"charge_id": f"ch-{len(calls)}"}

        @compensate("charge")
        async def refund(self, ctx):
            calls.append("refund")

        @action("ship", depends_on=["charge"])
        async def ship(self, ctx):
            calls.append("ship")
            if ship_fails:
                msg = "no stock"
                raise RuntimeError(msg)

    return Checkout


class TestRunsOnce:
    async def test_a_second_saga_with_the_key_reuses_the_stored_result(self, storage):
        calls: list[str] = []
        first = await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        second = await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        assert calls == ["charge", "ship", "ship"]  # charged once
        assert second["charge_id"] == first["charge_id"] == "ch-1"

    async def test_another_saga_class_with_the_same_key_reuses_it_too(self, storage):
        calls: list[str] = []
        await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})

        class Renewal(Saga):
            saga_name = "renewal"

            @action("bill", idempotency_key=lambda ctx: f"charge-{ctx['order_id']}")
            async def bill(self, ctx):
                calls.append("bill")

        result = await Renewal(config=config(storage)).run({"order_id": "o-1"})
        assert "bill" not in calls
        assert result["charge_id"] == "ch-1"

    async def test_a_different_key_runs(self, storage):
        calls: list[str] = []
        await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        await checkout(calls)(config=config(storage)).run({"order_id": "o-2"})
        assert calls.count("charge") == 2

    async def test_the_key_is_per_tenant(self, storage):
        calls: list[str] = []
        with tenant_scope("acme"):
            await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        with tenant_scope("globex"):
            await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        assert calls.count("charge") == 2

    async def test_a_step_without_a_key_runs_every_time(self, storage):
        calls: list[str] = []
        await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        assert calls.count("ship") == 2


class TestFailuresAndCompensation:
    async def test_a_step_that_raises_frees_its_key(self, storage):
        calls: list[str] = []
        with pytest.raises(SagaFailedError):
            await checkout(calls, charge_fails=True)(config=config(storage)).run(
                {"order_id": "o-1"}
            )
        await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        assert calls.count("charge") == 2  # the first attempt took no effect

    async def test_compensating_the_step_frees_its_key(self, storage):
        calls: list[str] = []
        with pytest.raises(SagaFailedError):
            await checkout(calls, ship_fails=True)(config=config(storage)).run({"order_id": "o-1"})
        assert calls == ["charge", "ship", "refund"]
        await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        assert calls.count("charge") == 2  # refunded, so charged again

    async def test_a_reused_step_is_compensated_if_this_saga_fails_later(self, storage):
        calls: list[str] = []
        await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        with pytest.raises(SagaFailedError):
            await checkout(calls, ship_fails=True)(config=config(storage)).run({"order_id": "o-1"})
        assert calls == ["charge", "ship", "ship", "refund"]
        assert await storage.load_saga_state(record_id("charge-o-1")) is None  # freed


class TestInDoubt:
    async def claim_like_a_crashed_run(self, storage, key: str) -> None:
        from sagaz.core.types import SagaStatus

        fields = {"key": key, "saga_id": "crashed-run", "step": "charge", "result": None}
        await storage.create_saga_state(
            record_id(key), STEP_KEY_RECORD_NAME, SagaStatus.EXECUTING, [], fields
        )

    async def test_a_key_held_by_an_unfinished_run_fails_the_step_without_running_it(self, storage):
        calls: list[str] = []
        await self.claim_like_a_crashed_run(storage, "charge-o-1")
        with pytest.raises(SagaFailedError) as raised:
            await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        assert calls == []
        cause = raised.value.__cause__
        assert isinstance(cause, StepInDoubtError)
        assert cause.key == "charge-o-1"
        assert cause.held_by == "crashed-run"
        assert await storage.load_saga_state(record_id("charge-o-1")) is not None  # still held

    async def test_releasing_the_key_lets_the_step_run(self, storage):
        calls: list[str] = []
        await self.claim_like_a_crashed_run(storage, "charge-o-1")
        assert await release_step_key("charge-o-1", storage) is True
        assert await release_step_key("charge-o-1", storage) is False
        await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        assert calls == ["charge", "ship"]

    async def test_a_cancelled_step_leaves_its_key_in_doubt(self, storage):
        started = asyncio.Event()

        class Slow(Saga):
            saga_name = "slow"

            @action("charge", idempotency_key="charge-{order_id}")
            async def charge(self, ctx):
                started.set()
                await asyncio.sleep(5)

        run = asyncio.create_task(Slow(config=config(storage)).run({"order_id": "o-1"}))
        await started.wait()
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        calls: list[str] = []
        with pytest.raises(SagaFailedError) as raised:
            await checkout(calls)(config=config(storage)).run({"order_id": "o-1"})
        assert isinstance(raised.value.__cause__, StepInDoubtError)
        assert calls == []

    async def test_two_concurrent_sagas_with_the_key_run_the_step_once(self, storage):
        calls: list[str] = []
        release = asyncio.Event()

        class Charge(Saga):
            saga_name = "charge"

            @action("charge", idempotency_key="charge-{order_id}")
            async def charge(self, ctx):
                calls.append("charge")
                await release.wait()

        first = asyncio.create_task(Charge(config=config(storage)).run({"order_id": "o-1"}))
        await asyncio.sleep(0.05)
        with pytest.raises(SagaFailedError) as raised:  # the first is still in the step
            await Charge(config=config(storage)).run({"order_id": "o-1"})
        assert isinstance(raised.value.__cause__, StepInDoubtError)
        release.set()
        await first
        assert calls == ["charge"]


class TestKeys:
    def test_a_format_string_is_filled_from_the_context(self):
        assert render_key("charge", "charge-{order_id}", {"order_id": "o-1"}) == "charge-o-1"

    def test_a_function_gets_the_context(self):
        assert render_key("charge", lambda ctx: ctx["a"] + ctx["b"], {"a": "x", "b": "y"}) == "xy"

    def test_a_missing_context_field_is_a_definition_error(self):
        with pytest.raises(SagaDefinitionError, match="needs 'order_id' in the saga context"):
            render_key("charge", "charge-{order_id}", {})

    @pytest.mark.parametrize("key", ["", lambda ctx: None])
    def test_an_empty_key_is_a_definition_error(self, key):
        with pytest.raises(SagaDefinitionError, match="non-empty string"):
            render_key("charge", key, {})

    def test_record_ids_are_reserved_and_fixed_length(self):
        short, long = record_id("a"), record_id("x" * 5000)
        assert short.startswith(STEP_KEY_RECORD_NAME)
        assert len(short) == len(long)
        assert short != long

    async def test_the_imperative_add_step_takes_a_key_too(self):
        calls: list[str] = []
        storage = InMemorySagaStorage()
        order = f"o-{uuid4().hex[:8]}"

        async def charge(ctx):
            calls.append("charge")
            return {"charge_id": "ch-1"}

        for _ in range(2):
            saga = Saga(config=config(storage))
            saga.add_step("charge", charge, idempotency_key="charge-{order_id}")
            await saga.run({"order_id": order})
        assert calls == ["charge"]

    async def test_without_a_storage_keys_live_with_the_configuration(self):
        # A SagaConfig without a storage makes an in-memory one of its own.
        calls: list[str] = []
        shared = config(None)
        for _ in range(2):
            await checkout(calls)(config=shared).run({"order_id": "o-1"})
        assert calls.count("charge") == 1
        await checkout(calls)(config=config(None)).run({"order_id": "o-1"})
        assert calls.count("charge") == 2  # another configuration, another memory
