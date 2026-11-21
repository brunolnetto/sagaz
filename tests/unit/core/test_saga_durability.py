"""A saga id runs once, progress is saved, and failures to save are not silent (#534, #535)."""

from __future__ import annotations

import asyncio
import os

import pytest

from sagaz import Saga, SagaConfig, action, compensate
from sagaz.core.exceptions import SagaAlreadyExistsError, SagaPersistenceError
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.types import SagaStatus
from tests.unit.core.storage.backends.test_saga_tenancy_redis_unit import FakeRedis, _b

PG_URL = os.environ.get("SAGAZ_TEST_POSTGRES_URL")


class FakeRedisNX(FakeRedis):
    async def hsetnx(self, key, field, value):
        record = self.data.setdefault(_b(key), {})
        if _b(field) in record:
            return 0
        record[_b(field)] = _b(value)
        return 1


async def make_storage(kind: str, tmp_path):
    if kind == "memory":
        return InMemorySagaStorage()
    if kind == "sqlite":
        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage

        return SQLiteSagaStorage(str(tmp_path / "sagas.db"))
    if kind == "redis":
        from sagaz.core.storage.backends.redis.saga import RedisSagaStorage

        storage = RedisSagaStorage("redis://fake", key_prefix=f"saga-{tmp_path.name}:")
        storage._redis = FakeRedisNX()
        return storage
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    return PostgreSQLSagaStorage(PG_URL)


BACKENDS = [
    "memory",
    "sqlite",
    "redis",
    pytest.param("postgresql", marks=pytest.mark.skipif(not PG_URL, reason="no PostgreSQL")),
]


@pytest.fixture(params=BACKENDS)
async def storage(request, tmp_path):
    storage = await make_storage(request.param, tmp_path)
    yield storage
    close = getattr(storage, "close", None)
    if close is not None:
        await close()


def unique(name: str) -> str:
    return f"{name}-{os.urandom(4).hex()}"


class TestCreateSagaState:
    async def test_only_the_first_create_succeeds(self, storage):
        saga_id = unique("c")
        args = (saga_id, "order", SagaStatus.EXECUTING, [], {"k": 1})
        assert await storage.create_saga_state(*args) is True
        assert await storage.create_saga_state(*args) is False
        assert (await storage.load_saga_state(saga_id))["context"] == {"k": 1}

    async def test_concurrent_creates_have_one_winner(self, storage):
        saga_id = unique("cc")
        results = await asyncio.gather(
            *(
                storage.create_saga_state(saga_id, "order", SagaStatus.EXECUTING, [], {"n": n})
                for n in range(5)
            )
        )
        assert sorted(results) == [False, False, False, False, True]

    async def test_the_default_checks_then_writes(self):
        """A third-party storage that only implements save/load still gets create."""
        from sagaz.core.storage.base import SagaStorage

        class Minimal(InMemorySagaStorage):
            create_saga_state = SagaStorage.create_saga_state

        storage = Minimal()
        assert await storage.create_saga_state("m", "order", SagaStatus.EXECUTING, [], {})
        assert not await storage.create_saga_state("m", "order", SagaStatus.EXECUTING, [], {})


def order_saga(calls: list[str], seen: dict | None = None, fail: str | None = None):
    class Order(Saga):
        saga_name = "order"

        @action("reserve", max_retries=0)
        async def reserve(self, ctx):
            calls.append("reserve")

        @compensate("reserve")
        async def release(self, ctx):
            calls.append("release")

        @action("charge", depends_on=["reserve"], max_retries=0)
        async def charge(self, ctx):
            calls.append("charge")
            if seen is not None:
                seen["during_charge"] = await self._config.storage.load_saga_state(self._saga_id)
            if fail == "charge":
                msg = "declined"
                raise ValueError(msg)

    return Order


def config(storage, **kwargs):
    return SagaConfig(storage=storage, metrics=False, logging=False, **kwargs)


class TestSagaIdRunsOnce:
    async def test_a_second_run_is_refused_before_any_step(self, storage):
        calls: list[str] = []
        saga_id = unique("o")
        await order_saga(calls)(config=config(storage)).run({}, saga_id=saga_id)
        with pytest.raises(SagaAlreadyExistsError) as raised:
            await order_saga(calls)(config=config(storage)).run({}, saga_id=saga_id)
        assert calls == ["reserve", "charge"]  # charged once
        assert (raised.value.saga_id, raised.value.status) == (saga_id, "completed")

    async def test_concurrent_runs_charge_once(self, storage):
        calls: list[str] = []
        saga_id = unique("o")
        results = await asyncio.gather(
            *(order_saga(calls)(config=config(storage)).run({}, saga_id=saga_id) for _ in range(4)),
            return_exceptions=True,
        )
        refused = [r for r in results if isinstance(r, SagaAlreadyExistsError)]
        assert (len(refused), calls.count("charge")) == (3, 1)

    async def test_an_explicit_rerun_runs_again(self):
        calls: list[str] = []
        storage = InMemorySagaStorage()
        await order_saga(calls)(config=config(storage)).run({}, saga_id="o")
        await order_saga(calls)(config=config(storage)).run({}, saga_id="o", allow_rerun=True)
        assert calls.count("charge") == 2

    async def test_generated_ids_never_collide(self):
        calls: list[str] = []
        storage = InMemorySagaStorage()
        for _ in range(3):
            await order_saga(calls)(config=config(storage)).run({})
        assert calls.count("charge") == 3


class TestProgressAndFailures:
    async def test_progress_is_saved_after_each_level(self):
        storage = InMemorySagaStorage()
        seen: dict = {}
        await order_saga([], seen)(config=config(storage)).run({}, saga_id="p")
        during = seen["during_charge"]
        assert during["status"] == SagaStatus.EXECUTING.value
        assert [(s["name"], s["status"]) for s in during["steps"]] == [("reserve", "completed")]

    async def test_a_failed_progress_save_stops_and_compensates(self):
        class FailsOnProgress(InMemorySagaStorage):
            async def save_saga_state(self, saga_id, name, status, *args, **kwargs):
                if status == SagaStatus.EXECUTING:
                    msg = "db down"
                    raise ConnectionError(msg)
                await super().save_saga_state(saga_id, name, status, *args, **kwargs)

        calls: list[str] = []
        storage = FailsOnProgress()
        with pytest.raises(SagaPersistenceError, match="progress"):
            await order_saga(calls)(config=config(storage)).run({}, saga_id="f")
        assert calls == ["reserve", "release"]  # charge never ran
        assert (await storage.load_saga_state("f"))["status"] == "rolled_back"

    async def test_tolerating_storage_errors_keeps_the_old_behavior(self):
        class Down(InMemorySagaStorage):
            async def create_saga_state(self, *args, **kwargs):
                msg = "db down"
                raise ConnectionError(msg)

            async def save_saga_state(self, *args, **kwargs):
                msg = "db down"
                raise ConnectionError(msg)

        calls: list[str] = []
        cfg = config(Down(), tolerate_persistence_errors=True)
        await order_saga(calls)(config=cfg).run({})
        assert calls == ["reserve", "charge"]


class TestOutboxStorageIsInitialized:
    async def test_the_listener_initializes_its_storage_once(self):
        from sagaz.core.listeners import OutboxSagaListener

        class Outbox:
            def __init__(self):
                self.initialized = 0
                self.events: list = []

            async def initialize(self):
                self.initialized += 1

            async def insert(self, event):
                assert self.initialized, "insert before initialize"
                self.events.append(event.event_type)

        outbox = Outbox()
        listener = OutboxSagaListener(storage=outbox)
        await asyncio.gather(
            listener.on_saga_complete("order", "s-1", {}),
            listener.on_saga_complete("order", "s-2", {}),
        )
        assert (outbox.initialized, len(outbox.events)) == (1, 2)

    @pytest.mark.skipif(not PG_URL, reason="no PostgreSQL")
    async def test_postgresql_outbox_initialize_is_idempotent(self):
        from sagaz.core.storage.backends.postgresql.outbox import PostgreSQLOutboxStorage

        outbox = PostgreSQLOutboxStorage(PG_URL)
        await outbox.initialize()
        pool = outbox._pool
        await outbox.initialize()
        assert outbox._pool is pool
        await outbox.close()
