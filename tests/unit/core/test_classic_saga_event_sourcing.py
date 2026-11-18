"""Event recording for the imperative ``sagaz.core.saga.Saga`` (#450)."""

from __future__ import annotations

import asyncio

import pytest
from click.testing import CliRunner

from sagaz.cli.app import cli
from sagaz.core.saga import Saga
from sagaz.core.storage.event_store import InMemoryEventStore
from sagaz.core.storage.event_store import recorder as recorder_module
from sagaz.core.storage.event_store.sqlite import SQLiteEventStore
from sagaz.core.types import SagaStatus
from sagaz.projections import load_projection


async def ok(ctx):
    return {"done": True}


async def declined(ctx):
    msg = "card declined"
    raise ValueError(msg)


async def undo(result, ctx):
    return None


async def broken_undo(result, ctx):
    msg = "cannot undo"
    raise RuntimeError(msg)


async def build(store, steps, *, dag=False, **options) -> Saga:
    saga = Saga(name="order", event_store=store, retry_backoff_base=0.001, **options)
    first = steps[0][0]
    for i, (name, action, compensation) in enumerate(steps):
        dependencies = (set() if i == 0 else {first}) if dag else None
        await saga.add_step(name, action, compensation, max_retries=1, dependencies=dependencies)
    return saga


async def run(store, steps, **options):
    saga = await build(store, steps, **options)
    result = await saga.execute()
    events = await store.load_stream(saga.saga_id)
    return result, [e.event_type for e in events], await load_projection(store, saga.saga_id)


@pytest.fixture
def store():
    return InMemoryEventStore()


class TestSequential:
    async def test_completed(self, store):
        result, types, state = await run(store, [("a", ok, undo), ("b", ok, undo)])
        assert result.status == SagaStatus.COMPLETED
        assert types == ["SagaStarted", "StepExecuted", "StepExecuted", "SagaCompleted"]
        assert state.status == "completed"
        assert state.steps["a"].result == {"done": True}
        assert state.saga_name == "order"

    async def test_rolled_back(self, store):
        result, types, state = await run(store, [("a", ok, undo), ("b", declined, undo)])
        assert result.status == SagaStatus.ROLLED_BACK
        assert types == [
            "SagaStarted",
            "StepExecuted",
            "StepFailed",
            "CompensationStarted",
            "StepCompensated",
            "SagaRolledBack",
        ]
        assert (state.status, state.failed_step) == ("rolled_back", "b")
        assert state.error == "ValueError: card declined"  # the user's error, not the wrapper
        assert state.steps["a"].status == "compensated"

    async def test_first_step_failure_has_nothing_to_compensate(self, store):
        result, types, state = await run(store, [("a", declined, undo)])
        assert result.status == SagaStatus.ROLLED_BACK
        assert types == ["SagaStarted", "StepFailed", "SagaRolledBack"]
        assert state.status == "rolled_back"

    async def test_compensation_failure(self, store):
        result, types, state = await run(store, [("a", ok, broken_undo), ("b", declined, undo)])
        assert result.status == SagaStatus.FAILED
        assert types[-2:] == ["StepCompensationFailed", "SagaFailed"]
        assert state.status == "failed"
        assert state.steps["a"].error == "RuntimeError: cannot undo"

    async def test_retries_record_one_outcome(self, store):
        attempts = []

        async def flaky(ctx):
            attempts.append(1)
            if len(attempts) == 1:
                msg = "transient"
                raise ConnectionError(msg)
            return {"ok": True}

        result, types, _ = await run(store, [("a", flaky, undo)])
        assert result.status == SagaStatus.COMPLETED
        assert types.count("StepExecuted") == 1
        assert "StepFailed" not in types

        _, types, _ = await run(InMemoryEventStore(), [("a", declined, undo)])
        assert types.count("StepFailed") == 1  # after both attempts


class TestDAG:
    async def test_completed(self, store):
        steps = [("a", ok, undo), ("b", ok, undo), ("c", ok, undo)]
        result, types, state = await run(store, steps, dag=True)
        assert result.status == SagaStatus.COMPLETED
        assert types.count("StepExecuted") == 3
        assert types[-1] == "SagaCompleted"
        assert state.steps["b"].duration_ms >= 0

    async def test_rolled_back(self, store):
        steps = [("a", ok, undo), ("b", declined, undo), ("c", ok, undo)]
        result, types, state = await run(store, steps, dag=True)
        assert result.status == SagaStatus.ROLLED_BACK
        assert types[:4] == ["SagaStarted", "StepExecuted", "StepExecuted", "StepFailed"]
        assert types[-1] == "SagaRolledBack"
        assert "CompensationStarted" in types
        assert (state.status, state.failed_step) == ("rolled_back", "b")

    async def test_first_batch_failure(self, store):
        result, types, state = await run(store, [("a", declined, undo), ("b", ok, undo)], dag=True)
        assert result.status == SagaStatus.ROLLED_BACK
        assert types[-1] == "SagaRolledBack"  # nothing was completed, nothing to undo
        assert state.status == "rolled_back"


class TestConfiguration:
    async def test_no_event_store_records_nothing(self):
        saga = Saga(name="plain")
        await saga.add_step("a", ok, undo)
        result = await saga.execute()
        assert result.status == SagaStatus.COMPLETED
        assert saga._recorder is None

    async def test_url_and_snapshots(self, monkeypatch):
        monkeypatch.setattr(recorder_module, "_stores_by_url", {})
        saga = await build("memory://", [("a", ok, undo), ("b", ok, undo)], snapshot_threshold=2)
        await saga.execute()
        store = recorder_module._stores_by_url["memory://"]
        assert (await store.load_latest_snapshot(saga.saga_id)).sequence == 4  # at 2 and 4
        assert (await load_projection(store, saga.saga_id)).status == "completed"

    def test_event_log_cli(self, tmp_path):
        path = tmp_path / "events.db"

        async def record() -> str:
            async with SQLiteEventStore(str(path)) as store:
                saga = await build(store, [("a", ok, undo), ("b", declined, undo)])
                await saga.execute()
            return saga.saga_id

        saga_id = asyncio.run(record())
        result = CliRunner().invoke(cli, ["event-log", saga_id, "--store-url", f"sqlite://{path}"])
        assert result.exit_code == 0, result.output
        assert result.output.splitlines()[0].endswith("(order, tenant default): rolled_back")
