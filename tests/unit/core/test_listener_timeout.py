"""An orchestrated saga's listeners cannot hold up its steps (#633)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sagaz import Saga, SagaConfig, action
from sagaz.core.listeners import Listeners, SagaListener, notify


class Slow(SagaListener):
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.finished: list[str] = []

    async def on_step_enter(self, saga_name: str, step_name: str, ctx: dict[str, Any]) -> None:
        await asyncio.sleep(self.seconds)
        self.finished.append(step_name)


class Recorder(SagaListener):
    def __init__(self) -> None:
        self.events: list[str] = []

    async def on_saga_complete(self, saga_name: str, saga_id: str, ctx: dict[str, Any]) -> None:
        self.events.append("complete")


class Order(Saga):
    saga_name = "order"

    @action("reserve")
    async def reserve(self, ctx: dict[str, Any]) -> dict[str, Any]:
        return {"reservation": "R1"}


def config(*listeners: SagaListener, timeout: float | None) -> SagaConfig:
    return SagaConfig(
        metrics=False, logging=False, extra_listeners=list(listeners), listener_timeout=timeout
    )


async def test_a_slow_listener_is_skipped_and_the_saga_completes(caplog):
    slow, recorder = Slow(60), Recorder()
    with caplog.at_level(logging.WARNING):
        result = await asyncio.wait_for(
            Order(config=config(slow, recorder, timeout=0.01)).run({}), 5
        )
    assert result["reservation"] == "R1"
    assert slow.finished == []  # cancelled
    assert recorder.events == ["complete"]  # the next listener still ran
    assert "Slow.on_step_enter took longer than 0.01s" in caplog.text


async def test_without_a_timeout_a_listener_is_awaited():
    slow = Slow(0.05)
    await Order(config=config(slow, timeout=None)).run({})
    assert slow.finished == ["reserve"]


def test_the_default_is_five_seconds():
    assert SagaConfig().listener_timeout == 5.0


def test_one_implementation_serves_both_modes():
    from sagaz.choreography import _observe

    assert _observe.notify is notify
    assert _observe.Listeners is Listeners


async def test_a_sync_listener_is_called_and_a_failing_one_is_skipped(caplog):
    calls: list[str] = []

    class Sync:
        def on_step_enter(self, *args: Any) -> None:
            calls.append("sync")

    class Broken:
        async def on_step_enter(self, *args: Any) -> None:
            msg = "listener bug"
            raise RuntimeError(msg)

    with caplog.at_level(logging.WARNING):
        await notify(Listeners([Broken(), Sync()]), "on_step_enter", "s", "x", {})
    assert calls == ["sync"]
    assert "Broken.on_step_enter error: listener bug" in caplog.text
