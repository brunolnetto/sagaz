"""Bugs found by the feature × mode audit, in sagaz.Saga (#550, #551, #552, #555)."""

from __future__ import annotations

from dataclasses import fields

import pytest

from sagaz import Saga, SagaConfig, SagaFailedError, SagaStatus, action, compensate
from sagaz.core.storage import InMemorySagaStorage


def config(**kwargs):
    return SagaConfig(metrics=False, logging=False, **kwargs)


def order_saga(undo_failures: int, *, compensation_retries: int = 3, attempts=None):
    attempts = attempts if attempts is not None else []

    class Order(Saga):
        saga_name = "order"
        retry_backoff_base = 0

        @action("reserve", max_retries=0)
        async def reserve(self, ctx): ...

        @compensate("reserve", max_retries=compensation_retries)
        async def release(self, ctx):
            attempts.append(1)
            if len(attempts) <= undo_failures:
                msg = "warehouse offline"
                raise RuntimeError(msg)

        @action("charge", depends_on=["reserve"], max_retries=0)
        async def charge(self, ctx):
            msg = "declined"
            raise ValueError(msg)

    return Order


class TestCompensationRetries:
    """#550: @compensate(max_retries=) is honored."""

    async def test_a_flaky_compensation_is_retried(self):
        attempts: list[int] = []
        with pytest.raises(SagaFailedError) as failure:
            await order_saga(2, attempts=attempts)(config=config()).run({})
        assert (len(attempts), failure.value.status) == (3, SagaStatus.ROLLED_BACK)

    async def test_retries_run_out(self):
        attempts: list[int] = []
        with pytest.raises(SagaFailedError) as failure:
            await order_saga(10, compensation_retries=1, attempts=attempts)(config=config()).run({})
        assert (len(attempts), failure.value.status) == (2, SagaStatus.FAILED)

    async def test_add_step_takes_compensation_retries(self):
        attempts: list[int] = []

        async def undo(ctx):
            attempts.append(1)
            msg = "no"
            raise RuntimeError(msg)

        async def boom(ctx):
            msg = "x"
            raise ValueError(msg)

        saga = Saga(name="adhoc", config=config())
        saga.retry_backoff_base = 0
        saga.add_step("a", lambda ctx: None, undo, max_retries=0, compensation_max_retries=0)
        saga.add_step("b", boom, depends_on=["a"], max_retries=0)
        with pytest.raises(SagaFailedError):
            await saga.run({})
        assert len(attempts) == 1


class TestOnExit:
    """#555: on_exit runs after a step, whatever its outcome."""

    async def test_on_exit_runs_after_success_and_failure(self):
        exits: list[str] = []

        def on_exit(ctx, name):
            exits.append(name)

        class S(Saga):
            saga_name = "s"

            @action("ok", on_exit=on_exit)
            async def ok(self, ctx): ...

            @action("bad", depends_on=["ok"], on_exit=on_exit, max_retries=0)
            async def bad(self, ctx):
                msg = "x"
                raise ValueError(msg)

        with pytest.raises(SagaFailedError):
            await S(config=config()).run({})
        assert exits == ["ok", "bad"]


class TestConfigCopies:
    """#552: with_storage()/with_broker() keep every field."""

    @pytest.mark.parametrize("copy", ["with_storage", "with_broker"])
    def test_every_field_survives(self, copy):
        from sagaz.core.outbox.brokers.memory import InMemoryBroker

        listener = object()
        original = config(
            extra_listeners=[listener],
            tolerate_persistence_errors=True,
            use_step_statechart=True,
            default_timeout=5,
            default_max_retries=1,
        )
        replacement = InMemorySagaStorage() if copy == "with_storage" else InMemoryBroker()
        copied = getattr(original, copy)(replacement)
        changed = {"storage", "broker", "outbox_storage"}
        assert [
            f.name
            for f in fields(original)
            if f.init
            and not f.name.startswith("_")
            and f.name not in changed
            and getattr(original, f.name) != getattr(copied, f.name)
        ] == []
        assert listener in copied.listeners


class TestTracingStatus:
    """#551: a FAILED saga is traced as failed, and a compensation span has its own error."""

    async def test_failed_compensation_is_traced(self):
        pytest.importorskip("opentelemetry.sdk")
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        from sagaz.core.listeners import TracingSagaListener
        from sagaz.observability.monitoring.tracing import SagaTracer

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = SagaTracer("order-service")
        tracer.tracer = provider.get_tracer("test")

        saga = order_saga(10, compensation_retries=0)(config=config())
        saga.add_listener(TracingSagaListener(tracer=tracer))
        with pytest.raises(SagaFailedError):
            await saga.run({})

        spans = {span.name: span for span in exporter.get_finished_spans()}
        assert spans["saga.execute.order"].attributes["saga.status"] == "failed"
        undo = spans["saga.step.compensation.reserve"]
        assert "warehouse offline" in undo.status.description
