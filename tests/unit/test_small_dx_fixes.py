"""Smaller developer-experience fixes (#538)."""

from __future__ import annotations

import asyncio

import pytest
from click.testing import CliRunner

from sagaz import Saga, SagaConfig, SagaFailedError, action, compensate, step


class Recorder:
    def __init__(self) -> None:
        self.events: list[str] = []

    def on_saga_complete(self, name, saga_id, ctx):
        self.events.append("complete")

    def on_step_failure(self, name, step_name, ctx, error):
        self.events.append(f"failure:{error}")


def config(**kwargs):
    return SagaConfig(metrics=False, logging=False, **kwargs)


class Order(Saga):
    saga_name = "order"

    @action("reserve")
    async def reserve(self, ctx):
        return {"reservation": "R1"}

    @compensate("reserve")
    async def release(self, ctx): ...


async def test_extra_listeners_join_the_configured_ones():
    extra = Recorder()
    cfg = SagaConfig(metrics=False, logging=True, extra_listeners=[extra])
    names = [type(listener).__name__ for listener in cfg.listeners]
    assert names == ["LoggingSagaListener", "Recorder"]
    await Order(config=cfg).run({})
    assert extra.events == ["complete"]


async def test_add_listener_keeps_the_saga_s_listeners():
    added = Recorder()
    saga = Order(config=SagaConfig(metrics=False, logging=True)).add_listener(added)
    assert [type(x).__name__ for x in saga._instance_listeners] == [
        "LoggingSagaListener",
        "Recorder",
    ]
    await saga.run({})
    assert added.events == ["complete"]


async def test_run_returns_no_internal_markers():
    result = await Order(config=config()).run({"order_id": 1})
    assert result == {"order_id": 1, "saga_id": result["saga_id"], "reservation": "R1"}


async def test_a_timeout_reaches_listeners_with_its_message():
    recorder = Recorder()

    class Slow(Saga):
        saga_name = "slow"

        @action("wait", timeout_seconds=0.01, max_retries=0)
        async def wait(self, ctx):
            await asyncio.sleep(1)

    with pytest.raises(SagaFailedError):
        await Slow(config=config()).add_listener(recorder).run({})
    assert recorder.events == ["failure:Step 'wait' timed out after 0.01s"]


def test_step_is_exported():
    assert step is action


def test_two_prometheus_metrics_in_their_own_registries():
    prometheus = pytest.importorskip("prometheus_client")
    from sagaz.observability.monitoring.prometheus import PrometheusMetrics

    first = PrometheusMetrics(registry=prometheus.CollectorRegistry())
    second = PrometheusMetrics(registry=prometheus.CollectorRegistry())
    assert first is not second


def test_saga_show(tmp_path):
    from sagaz.cli.app import cli
    from sagaz.core.storage import create_storage_manager

    url = f"sqlite:///{tmp_path / 'sagas.db'}"

    async def record():
        manager = create_storage_manager(url)
        await manager.initialize()
        try:
            await Order(config=config(storage=manager.saga)).run({"k": 1}, saga_id="o-1")
        finally:
            await manager.close()

    asyncio.run(record())
    runner = CliRunner()
    shown = runner.invoke(cli, ["saga", "show", "o-1", "--storage-url", url])
    assert shown.exit_code == 0, shown.output
    assert "completed" in shown.output
    assert "reserve" in shown.output
    as_json = runner.invoke(cli, ["saga", "show", "o-1", "--storage-url", url, "--json"])
    assert '"saga_id": "o-1"' in as_json.output
    missing = runner.invoke(cli, ["saga", "show", "nope", "--storage-url", url])
    assert missing.exit_code == 1
    assert "no saga 'nope'" in missing.output


def test_saga_show_hides_passwords():
    from sagaz.cli.saga import _redacted

    assert _redacted("postgresql://app:s3cret@db/x") == "postgresql://app:***@db/x"
    assert _redacted("sqlite:///x.db") == "sqlite:///x.db"
