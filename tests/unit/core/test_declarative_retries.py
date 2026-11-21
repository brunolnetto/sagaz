"""Declarative steps retry, and take their defaults from SagaConfig (#533)."""

from __future__ import annotations

import asyncio

import pytest

from sagaz import Saga, SagaConfig, action, compensate
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage


def config(**kwargs):
    return SagaConfig(metrics=False, logging=False, **kwargs)


def flaky(failures: int, calls: list[int]):
    async def run(self, ctx):
        calls.append(1)
        if len(calls) <= failures:
            msg = "down"
            raise ConnectionError(msg)
        return {"ok": True}

    return run


@pytest.mark.parametrize(("failures", "succeeds"), [(0, True), (3, True), (4, False)])
async def test_a_step_is_attempted_max_retries_plus_one_times(failures, succeeds):
    calls: list[int] = []

    class S(Saga):
        saga_name = "s"
        retry_backoff_base = 0
        a = action("a", max_retries=3)(flaky(failures, calls))

    if succeeds:
        assert (await S(config=config()).run({}))["ok"] is True
    else:
        with pytest.raises(ConnectionError):
            await S(config=config()).run({})
    assert len(calls) == min(failures + 1, 4)


async def test_the_config_defaults_apply_when_the_step_sets_none():
    calls: list[int] = []

    class S(Saga):
        saga_name = "s"
        retry_backoff_base = 0
        a = action("a")(flaky(10, calls))

    with pytest.raises(ConnectionError):
        await S(config=config(default_max_retries=1)).run({})
    assert len(calls) == 2

    class Slow(Saga):
        saga_name = "slow"

        @action("a", max_retries=0)
        async def a(self, ctx):
            await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        await Slow(config=config(default_timeout=0.05)).run({})


async def test_a_timed_out_attempt_is_retried():
    calls: list[int] = []

    class S(Saga):
        saga_name = "s"
        retry_backoff_base = 0

        @action("a", timeout_seconds=0.05, max_retries=1)
        async def a(self, ctx):
            calls.append(1)
            if len(calls) == 1:
                await asyncio.sleep(1)
            return {"ok": True}

    assert (await S(config=config()).run({}))["ok"] is True
    assert len(calls) == 2


async def test_hooks_listeners_and_compensation_see_one_failure():
    events: list[str] = []

    class Listener:
        def on_step_failure(self, *args):
            events.append("listener:failure")

    async def on_enter(ctx, name):
        events.append("enter")

    async def on_failure(ctx, name, error):
        events.append("failure")

    class S(Saga):
        saga_name = "s"
        retry_backoff_base = 0
        listeners = [Listener()]

        @action("first")
        async def first(self, ctx):
            return None

        @compensate("first")
        async def undo_first(self, ctx):
            events.append("undo:first")

        @action("a", depends_on=["first"], max_retries=2, on_enter=on_enter, on_failure=on_failure)
        async def a(self, ctx):
            events.append("attempt")
            msg = "down"
            raise ConnectionError(msg)

    with pytest.raises(ConnectionError):
        await S(config=config()).run({})
    assert events == [
        "enter",
        "attempt",
        "attempt",
        "attempt",
        "failure",
        "listener:failure",
        "undo:first",
    ]


async def test_the_stored_retry_count_is_the_last_attempt():
    storage = InMemorySagaStorage()
    calls: list[int] = []

    class S(Saga):
        saga_name = "s"
        retry_backoff_base = 0
        a = action("a", max_retries=3)(flaky(2, calls))

    await S(config=config(storage=storage)).run({}, saga_id="r-1")
    step = (await storage.load_saga_state("r-1"))["steps"][0]
    assert (step["status"], step["retry_count"]) == ("completed", 2)


async def test_cancellation_is_not_retried():
    calls: list[int] = []
    started = asyncio.Event()

    class S(Saga):
        saga_name = "s"

        @action("a", max_retries=5)
        async def a(self, ctx):
            calls.append(1)
            started.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(S(config=config()).run({}))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) == 1
