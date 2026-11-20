"""A background loop that stops between iterations (#500)."""

from __future__ import annotations

import asyncio
import logging

from sagaz.core._poller import Poller


async def test_stop_waits_for_the_iteration_in_progress():
    events: list[str] = []
    started = asyncio.Event()

    async def step():
        events.append("start")
        started.set()
        await asyncio.sleep(0.05)  # e.g. a database call
        events.append("end")

    poller = Poller(step, 10, name="test")
    poller.start()
    await started.wait()
    await poller.stop()
    assert events == ["start", "end"]  # finished, not cancelled half-way
    assert not poller.running


async def test_an_iteration_overrunning_the_grace_is_cancelled(caplog):
    cancelled = asyncio.Event()

    async def step():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    poller = Poller(step, 10, grace=0.05, name="slow")
    poller.start()
    await asyncio.sleep(0.01)
    with caplog.at_level(logging.WARNING):
        await poller.stop()
    assert cancelled.is_set()
    assert "slow: iteration overran" in caplog.text


async def test_failures_are_logged_and_the_loop_goes_on(caplog):
    calls = 0

    async def step():
        nonlocal calls
        calls += 1
        if calls == 1:
            msg = "boom"
            raise RuntimeError(msg)

    poller = Poller(step, lambda: 0.01, name="flaky")  # the interval is read each time
    with caplog.at_level(logging.ERROR):
        poller.start()
        poller.start()  # already running
        for _ in range(100):
            if calls >= 3:
                break
            await asyncio.sleep(0.01)
        await poller.stop()
    assert calls >= 3
    assert "flaky: iteration failed" in caplog.text


async def test_stop_before_start_and_restart():
    calls = 0

    async def step():
        nonlocal calls
        calls += 1

    poller = Poller(step, 10)
    await poller.stop()  # nothing to stop
    poller.start()
    await asyncio.sleep(0.01)
    await poller.stop()
    poller.start()  # starts again after a stop
    await asyncio.sleep(0.01)
    await poller.stop()
    assert calls == 2
