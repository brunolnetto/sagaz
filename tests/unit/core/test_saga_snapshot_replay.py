"""Snapshots and replay on ``sagaz.Saga`` (#544)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from sagaz import ReplayConfig, Saga, SagaFailedError, SnapshotStrategy, action, compensate
from sagaz.core.config import SagaConfig
from sagaz.core.decorators._snapshots import snapshot_saga_id
from sagaz.core.replay import ReplayStatus
from sagaz.core.replay.saga_replay import SagaReplay
from sagaz.core.replay.time_travel import SagaTimeTravel
from sagaz.core.storage.backends.memory_snapshot import InMemorySnapshotStorage


def config(snapshots, strategy=SnapshotStrategy.BEFORE_EACH_STEP, **more) -> SagaConfig:
    return SagaConfig(
        metrics=False,
        logging=False,
        default_max_retries=0,
        replay_config=ReplayConfig(enable_snapshots=True, snapshot_strategy=strategy),
        snapshot_storage=snapshots,
        **more,
    )


def order(calls: list[str]):
    """reserve -> charge -> ship; charge fails unless the context has a good token."""

    class Order(Saga):
        saga_name = "order"

        @action("reserve")
        async def reserve(self, ctx):
            calls.append("reserve")
            return {"reserved": True}

        @compensate("reserve")
        async def release(self, ctx):
            calls.append("undo:reserve")

        @action("charge", depends_on=["reserve"])
        async def charge(self, ctx):
            calls.append("charge")
            if ctx.get("token") != "good":
                msg = "card declined"
                raise RuntimeError(msg)
            return {"charged": True}

        @compensate("charge")
        async def refund(self, ctx):
            calls.append("undo:charge")

        @action("ship", depends_on=["charge"])
        async def ship(self, ctx):
            calls.append("ship")
            if ctx.get("no_truck"):
                msg = "no truck"
                raise RuntimeError(msg)

    return Order


async def snapshots_of(storage, saga_id: str):
    found = await storage.list_snapshots(snapshot_saga_id(saga_id))
    return sorted(found, key=lambda s: (s.created_at, s.step_index))


class TestCapture:
    async def test_before_each_step(self):
        storage = InMemorySnapshotStorage()
        await order([])(config=config(storage)).run({"token": "good"}, saga_id="o-1")
        taken = await snapshots_of(storage, "o-1")
        assert [s.step_name for s in taken] == ["reserve", "charge", "ship"]
        assert [s.completed_steps for s in taken] == [[], ["reserve"], ["reserve", "charge"]]
        assert [s.step_index for s in taken] == [0, 1, 2]
        assert taken[1].saga_name == "order"
        assert taken[1].context["reserved"] is True
        assert taken[1].status == "executing"

    async def test_after_each_step(self):
        storage = InMemorySnapshotStorage()
        cfg = config(storage, SnapshotStrategy.AFTER_EACH_STEP)
        await order([])(config=cfg).run({"token": "good"}, saga_id="o-1")
        taken = await snapshots_of(storage, "o-1")
        assert [s.completed_steps for s in taken] == [
            ["reserve"],
            ["reserve", "charge"],
            ["reserve", "charge", "ship"],
        ]

    async def test_on_completion_and_on_failure(self):
        done, failed = InMemorySnapshotStorage(), InMemorySnapshotStorage()
        await order([])(config=config(done, SnapshotStrategy.ON_COMPLETION)).run(
            {"token": "good"}, saga_id="o-1"
        )
        (completed,) = await snapshots_of(done, "o-1")
        assert completed.status == "completed"
        assert completed.completed_steps == ["reserve", "charge", "ship"]

        with pytest.raises(SagaFailedError):
            await order([])(config=config(failed, SnapshotStrategy.ON_FAILURE)).run(
                {"token": "bad"}, saga_id="o-2"
            )
        (failure,) = await snapshots_of(failed, "o-2")
        assert (failure.status, failure.step_name) == ("failed", "charge")
        assert failure.completed_steps == ["reserve"]  # taken before compensating
        assert await snapshots_of(done, "o-2") == []  # a failed run takes no completion snapshot

    async def test_nothing_is_captured_unless_enabled(self):
        storage = InMemorySnapshotStorage()
        off = SagaConfig(
            metrics=False,
            logging=False,
            replay_config=ReplayConfig(enable_snapshots=False),
            snapshot_storage=storage,
        )
        await order([])(config=off).run({"token": "good"}, saga_id="o-1")
        plain = SagaConfig(metrics=False, logging=False)
        await order([])(config=plain).run({"token": "good"}, saga_id="o-2")
        assert await snapshots_of(storage, "o-1") == []

    async def test_a_snapshot_that_cannot_be_saved_does_not_stop_the_run(self):
        class Broken(InMemorySnapshotStorage):
            async def save_snapshot(self, snapshot):
                msg = "disk full"
                raise OSError(msg)

        context = await order([])(config=config(Broken())).run({"token": "good"})
        assert context["charged"] is True

    def test_a_saga_id_maps_to_a_stable_uuid(self):
        real = uuid4()
        assert snapshot_saga_id(real) == real
        assert snapshot_saga_id(str(real)) == real
        named = snapshot_saga_id("order-42")
        assert isinstance(named, UUID)
        assert named == snapshot_saga_id("order-42")
        assert named != snapshot_saga_id("order-43")


class TestRunFromSnapshot:
    async def failed_at_charge(self):
        storage = InMemorySnapshotStorage()
        with pytest.raises(SagaFailedError):
            await order([])(config=config(storage)).run({"token": "bad", "order": 7}, saga_id="o-1")
        return storage, await storage.get_latest_snapshot(snapshot_saga_id("o-1"), "charge")

    async def test_completed_steps_are_adopted_and_the_rest_run(self):
        storage, snapshot = await self.failed_at_charge()
        calls: list[str] = []
        context = await order(calls)(config=config(storage)).run_from_snapshot(
            snapshot, {"token": "good"}, saga_id="o-1-replay"
        )
        assert calls == ["charge", "ship"]  # reserve was not run again
        assert context["saga_id"] == "o-1-replay"
        assert (context["order"], context["reserved"], context["charged"]) == (7, True, True)

    async def test_a_failed_replay_compensates_the_adopted_steps_too(self):
        storage, snapshot = await self.failed_at_charge()
        calls: list[str] = []
        with pytest.raises(SagaFailedError):
            await order(calls)(config=config(storage)).run_from_snapshot(
                snapshot, {"token": "good", "no_truck": True}
            )
        assert calls == ["charge", "ship", "undo:charge", "undo:reserve"]

    async def test_a_snapshot_of_another_saga_is_refused(self):
        storage, snapshot = await self.failed_at_charge()

        class Other(Saga):
            saga_name = "other"

            @action("a")
            async def a(self, ctx): ...

        with pytest.raises(ValueError, match=r"does not define: \['reserve'\]"):
            await Other(config=config(storage)).run_from_snapshot(snapshot)

    async def test_steps_of_a_parallel_level_are_adopted_one_by_one(self):
        calls: list[str] = []
        storage = InMemorySnapshotStorage()

        class Fanout(Saga):
            saga_name = "fanout"

            @action("a")
            async def a(self, ctx):
                calls.append("a")

            @action("b")
            async def b(self, ctx):
                await asyncio.sleep(0.02)
                calls.append("b")
                if ctx.get("b_fails"):
                    msg = "b failed"
                    raise RuntimeError(msg)

            @action("join", depends_on=["a", "b"])
            async def join(self, ctx):
                calls.append("join")

        cfg = config(storage, SnapshotStrategy.ON_FAILURE, failure_strategy="WAIT_ALL")
        with pytest.raises(SagaFailedError):
            await Fanout(config=cfg).run({"b_fails": True}, saga_id="f-1")
        snapshot = await storage.get_latest_snapshot(snapshot_saga_id("f-1"))
        assert snapshot.completed_steps == ["a"]
        calls.clear()
        await Fanout(config=cfg).run_from_snapshot(snapshot, {"b_fails": False})
        assert calls == ["b", "join"]


class TestSagaReplay:
    async def test_from_checkpoint_runs_a_sagaz_saga(self):
        storage, _ = await TestRunFromSnapshot().failed_at_charge()
        calls: list[str] = []
        replay = SagaReplay(
            "o-1", storage, saga_factory=lambda name: order(calls)(config=config(storage))
        )
        result = await replay.from_checkpoint("charge", {"token": "good"})
        assert result.replay_status == ReplayStatus.SUCCESS
        assert calls == ["charge", "ship"]
        assert result.original_saga_id == snapshot_saga_id("o-1")
        assert await snapshots_of(storage, str(result.new_saga_id))  # the replay is a new run

    async def test_a_replay_that_fails_is_reported_failed(self):
        storage, _ = await TestRunFromSnapshot().failed_at_charge()
        replay = SagaReplay(
            "o-1", storage, saga_factory=lambda name: order([])(config=config(storage))
        )
        result = await replay.from_checkpoint("charge", {"token": "still bad"})
        assert result.replay_status == ReplayStatus.FAILED
        assert "card declined" in result.error_message

    async def test_checkpoints_and_dry_run(self):
        storage, _ = await TestRunFromSnapshot().failed_at_charge()
        replay = SagaReplay("o-1", storage)
        checkpoints = await replay.list_available_checkpoints()
        assert {c["step_name"] for c in checkpoints} == {"reserve", "charge"}
        result = await replay.from_checkpoint("charge", dry_run=True)
        assert result.replay_status == ReplayStatus.SUCCESS


async def test_time_travel_reads_the_same_snapshots():
    storage = InMemorySnapshotStorage()
    await order([])(config=config(storage)).run({"token": "good"}, saga_id="o-1")
    travel = SagaTimeTravel("o-1", storage)
    state = await travel.get_state_at(datetime.now(UTC) + timedelta(seconds=1))
    assert state is not None
    assert state.current_step == "ship"
    assert await travel.get_state_at(datetime.now(UTC) - timedelta(hours=1)) is None
