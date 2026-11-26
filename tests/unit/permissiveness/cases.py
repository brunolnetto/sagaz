"""Definitions and calls that cannot be right, for the permissiveness inventory (#660).

Each case builds or calls something with an invalid value, and raises if sagaz refuses
it. ``test_inventory`` runs them and compares what sagaz accepts with
``known_accepted.json``: a case sagaz starts to refuse must leave that file, and a case
it starts to accept must be fixed, not added.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sagaz import ReplayConfig, Saga, SagaConfig, action, compensate, forward_recovery
from sagaz.choreography import (
    ChoreographedSaga,
    ChoreographyEngine,
    Event,
    EventBus,
    create_event_bus,
)
from sagaz.choreography.state import create_participant_state
from sagaz.choreography.state.memory import InMemoryParticipantState
from sagaz.choreography.tracker import ChoreographyTracker
from sagaz.core.listeners._notify import Listeners
from sagaz.core.outbox.types import OutboxConfig
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage
from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage
from sagaz.core.storage.backends.redis.saga import RedisSagaStorage
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
from sagaz.core.storage.event_store._factory import create_event_store
from sagaz.core.storage.saga_log import create_saga_log_store
from sagaz.core.strategies.fail_fast_grace import FailFastWithGraceStrategy
from sagaz.core.tenant import TenantContext, TenantQuotas
from sagaz.testing import ChaosMonkey

#: what -> the callable that tries it. Keys are the ids used in known_accepted.json.
CASES: dict[str, Callable[[], Any]] = {}


def case(what: str) -> Callable[[Callable[[], Any]], Callable[[], Any]]:
    def register(fn: Callable[[], Any]) -> Callable[[], Any]:
        assert what not in CASES, what
        CASES[what] = fn
        return fn

    return register


def accepted(fn: Callable[[], Any]) -> bool:
    """Whether sagaz accepts the case: *fn* (sync, or returning a coroutine) does not raise."""
    try:
        out = fn()
        if asyncio.iscoroutine(out):
            asyncio.run(out)
    except Exception:
        return False
    return True


def quiet(**settings: Any) -> SagaConfig:
    return SagaConfig(metrics=False, logging=False, default_max_retries=0, **settings)


async def noop(ctx):
    return {}


async def handler(event, me): ...


def saga_with(*steps: tuple[Any, ...], **step_options: Any) -> Saga:
    saga = Saga(config=quiet())
    for step in steps:
        saga.add_step(*step, **step_options)
    return saga


# ------------------------------------------------- a string where a list of names is expected


@case('add_step(depends_on="reserve")')
def _():
    saga = saga_with(("reserve", noop))
    saga.add_step("charge", noop, depends_on="reserve")


@case('@action("charge", depends_on="reserve")')
def _():
    class S(Saga):
        @action("reserve")
        async def reserve(self, ctx): ...

        @action("charge", depends_on="reserve")
        async def charge(self, ctx): ...

    S()


@case('ChoreographyEngine(completion_events="order.completed")')
def _():
    ChoreographyEngine(EventBus(), completion_events="order.completed")


@case('ChoreographyTracker(completion_events="order.completed")')
def _():
    ChoreographyTracker(EventBus(), completion_events="order.completed")


@case('participant.on("x", handler, emits="stock.reserved")')
def _():
    ChoreographedSaga(name="p").on("x", handler, emits="stock.reserved")


@case("ChoreographyEngine(listeners=<one listener, not a list>)")
def _():
    ChoreographyEngine(EventBus(), listeners=object())


# ------------------------------------------------------------------------- saga definitions


@case("@action on a method named _charge")
def _():
    class S(Saga):
        @action("charge")
        async def _charge(self, ctx): ...

    return S(config=quiet()).run({})


@case("a saga with no steps runs")
def _():
    return Saga(config=quiet()).run({})


@case('@compensate("chrage") for a step that does not exist')
def _():
    class S(Saga):
        @action("charge")
        async def charge(self, ctx): ...

        @compensate("chrage")
        async def refund(self, ctx): ...

    S()


@case("two @compensate for the same step")
def _():
    class S(Saga):
        @action("charge")
        async def charge(self, ctx): ...

        @compensate("charge")
        async def refund(self, ctx): ...

        @compensate("charge")
        async def refund_again(self, ctx): ...

    S()


@case("two @action with the same step name")
def _():
    class S(Saga):
        @action("charge")
        async def charge(self, ctx): ...

        @action("charge")
        async def charge_again(self, ctx): ...

    S()


@case('@forward_recovery("chrage") for a step that does not exist')
def _():
    class S(Saga):
        @action("charge")
        async def charge(self, ctx): ...

        @forward_recovery("chrage")
        async def recover(self, ctx, error): ...

    S()


@case('depends_on=["reserv"] is accepted when the saga is created')
def _():
    class S(Saga):
        @action("charge", depends_on=["reserv"])
        async def charge(self, ctx): ...

    S()


@case("@action(timeout_seconds=-1, max_retries=-2)")
def _():
    class S(Saga):
        @action("a", timeout_seconds=-1, max_retries=-2)
        async def a(self, ctx): ...

    S()


@case('@action("") with an empty step name')
def _():
    class S(Saga):
        @action("")
        async def a(self, ctx): ...

    S()


@case('add_step("a", "not callable")')
def _():
    saga_with(("a", "not callable"))


@case('class attribute deadline = "soon"')
def _():
    class S(Saga):
        deadline = "soon"

    S()


@case('class attribute retry_backoff_base = "fast"')
def _():
    class S(Saga):
        retry_backoff_base = "fast"

    S()


# ------------------------------------------------------------------------------ run() inputs


@case('run({}, saga_id="")')
def _():
    return Saga(config=quiet()).run({}, saga_id="")


@case("run({}, saga_id=12345)")
def _():
    return Saga(config=quiet()).run({}, saga_id=12345)


@case("a step returns a list, not a dict")
def _():
    async def step(ctx):
        return ["charged", 42]

    return saga_with(("a", step)).run({})


@case('a step returns {"saga_id": ..., "tenant_id": ...}')
def _():
    async def step(ctx):
        return {"saga_id": "hijacked", "tenant_id": "other"}

    return saga_with(("a", step)).run({}, saga_id="s-1")


# ----------------------------------------------------------------------------- configuration


@case("SagaConfig(failure_strategy=42)")
def _():
    quiet(failure_strategy=42)


@case('SagaConfig(storage_layout="unifed")')
def _():
    quiet(storage_layout="unifed")


@case('SagaConfig(storage_strategy="event-sourced")')
def _():
    quiet(storage_strategy="event-sourced")


@case('SagaConfig(storage="postgresql://...") with a URL, not a storage')
def _():
    quiet(storage="postgresql://x/y")


@case("SagaConfig(tenant_registry={})")
def _():
    quiet(tenant_registry={})


@case('ReplayConfig(snapshot_strategy="before_each_setp")')
def _():
    ReplayConfig(enable_snapshots=True, snapshot_strategy="before_each_setp")


@case("snapshots enabled without a snapshot storage")
def _():
    quiet(replay_config=ReplayConfig(enable_snapshots=True))


@case('SagaConfig(replay_config={"enable_snapshots": True}) with a dict')
def _():
    quiet(replay_config={"enable_snapshots": True})


@case("sagaz.yaml with misspelled keys")
def _():
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as file:
        file.write("default_timout: 5\nfailure_stratgy: WAIT_ALL\n")
    try:
        SagaConfig.from_file(file.name)
    finally:
        Path(file.name).unlink()


@case("SAGAZ_DEFAULT_TIMEOUT=abc and SAGAZ_METRICS_ENABLED=maybe")
def _():
    invalid = {"SAGAZ_DEFAULT_TIMEOUT": "abc", "SAGAZ_METRICS_ENABLED": "maybe"}
    os.environ.update(invalid)
    try:
        SagaConfig.from_env(load_dotenv=False)
    finally:
        for name in invalid:
            os.environ.pop(name)


@case("ReplayConfig(retention_days=-30)")
def _():
    ReplayConfig(retention_days=-30)


@case("OutboxConfig(batch_size=0)")
def _():
    OutboxConfig(batch_size=0)


@case("OutboxConfig(max_retries=-1)")
def _():
    OutboxConfig(max_retries=-1)


@case("OutboxConfig(poll_interval_seconds=0)")
def _():
    OutboxConfig(poll_interval_seconds=0)


# ------------------------------------------------------------------------------ choreography


def engine_case(parameter: str, value: Any) -> None:
    @case(f"ChoreographyEngine({parameter}={value!r})")
    def _():
        ChoreographyEngine(EventBus(), **{parameter: value})


for _parameter in (
    "deadline_poll_interval",
    "deadline_lease",
    "relay_interval",
    "default_max_retries",
    "default_timeout",
    "delivery_lease",
    "retry_backoff_base",
    "listener_timeout",
):
    engine_case(_parameter, -1)
engine_case("default_timeout", 0)


@case('ChoreographedSaga(name="")')
def _():
    ChoreographedSaga(name="")


@case('participant.on("", handler) with an empty event type')
def _():
    ChoreographedSaga(name="p").on("", handler)


@case('participant.on("x", "not callable")')
def _():
    ChoreographedSaga(name="p").on("x", "nope")


@case("two participants registered with the same name")
def _():
    engine = ChoreographyEngine(EventBus())
    engine.register(ChoreographedSaga(name="inventory").on("a", handler))
    engine.register(ChoreographedSaga(name="inventory").on("b", handler))


@case('Event("") with an empty type')
def _():
    Event("")


@case('Event("x", data="not a dict")')
def _():
    Event("x", data="nope")


@case('Event("x", tenant_id="Not Valid!")')
def _():
    Event("x", tenant_id="Not Valid!")


async def _begin(event_type: str, **options: Any) -> None:
    engine = ChoreographyEngine(EventBus())
    orders = ChoreographedSaga(name="orders")
    engine.register(orders)
    await engine.start()
    try:
        await orders.begin(event_type, **options)
    finally:
        await engine.stop()


@case('begin("order.created", deadline=-5)')
def _():
    return _begin("order.created", deadline=-5)


@case('begin("order.craeted") for an event type nobody handles')
def _():
    return _begin("order.craeted")


@case("ChoreographyTracker(stall_after=-10)")
def _():
    ChoreographyTracker(EventBus(), stall_after=-10)


@case("ChoreographyTracker(listener_timeout=-1)")
def _():
    ChoreographyTracker(EventBus(), listener_timeout=-1)


@case("InMemoryParticipantState(max_transactions=-1)")
def _():
    InMemoryParticipantState(max_transactions=-1)


@case("InMemoryParticipantState(max_deliveries=-1)")
def _():
    InMemoryParticipantState(max_deliveries=-1)


# ---------------------------------------------------------------- constructors and storage


@case("Listeners(timeout=-1)")
def _():
    Listeners([], timeout=-1)


@case("ChaosMonkey(failure_rate=5)")
def _():
    ChaosMonkey(failure_rate=5)


@case("ChaosMonkey(timeout_probability=-1)")
def _():
    ChaosMonkey(timeout_probability=-1)


@case("FailFastWithGraceStrategy(grace_period=-1)")
def _():
    FailFastWithGraceStrategy(grace_period=-1)


@case("RedisSagaStorage(url, default_ttl=-1)")
def _():
    RedisSagaStorage("redis://localhost:1", default_ttl=-1)


@case("PostgreSQLSagaStorage(url, pool_min_size=10, pool_max_size=1)")
def _():
    PostgreSQLSagaStorage("postgresql://x@localhost:1/y", pool_min_size=10, pool_max_size=1)


@case("PostgreSQLSagaStorage(url, pool_max_size=-1)")
def _():
    PostgreSQLSagaStorage("postgresql://x@localhost:1/y", pool_max_size=-1)


@case('SQLiteSagaStorage("") with an empty path')
def _():
    SQLiteSagaStorage("")


@case("storage.list_sagas(limit=-1)")
def _():
    return InMemorySagaStorage().list_sagas(limit=-1)


@case("TenantQuotas(max_retries=True)")
def _():
    TenantQuotas(max_retries=True)


@case("TenantQuotas(max_concurrent_sagas=-3)")
def _():
    TenantQuotas(max_concurrent_sagas=-3)


@case('TenantContext("acme", quotas={...}) with a dict')
def _():
    TenantContext("acme", quotas={"max_retries": 1})


# ------------------------------------------------------------------------------ URL factories


def url_case(label: str, factory: Callable[[str], Any], url: str) -> None:
    @case(f'{label}("{url}")')
    def _():
        factory(url)


url_case("create_saga_log_store", create_saga_log_store, "postgres-ql://x")
url_case("create_saga_log_store", create_saga_log_store, "")
url_case("create_event_store", create_event_store, "mysql://x")
url_case("create_participant_state", create_participant_state, "redis://x")
url_case("create_participant_state", create_participant_state, "justaname")
url_case("create_event_bus", create_event_bus, "nats://x")
