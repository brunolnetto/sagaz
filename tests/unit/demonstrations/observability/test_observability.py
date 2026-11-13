"""Tests for the otel_tracing demonstration."""

from __future__ import annotations

import pytest

from sagaz.demonstrations.observability.otel_tracing import main as demo


def _span(name, *, span_id, parent_id=None, status="OK", **attributes):
    return demo.SpanView(name, status, span_id, parent_id, attributes)


async def _traces():
    collector = demo.InMemoryCollector("test-service")
    saga_cls = demo.build_order_saga(demo.TracingSagaListener(tracer=collector.tracer))
    assert await demo.run_checkout(saga_cls, "o-1", carrier="up") == "completed"
    happy = collector.drain()
    assert await demo.run_checkout(saga_cls, "o-2", carrier="down") == "rolled_back"
    return happy, collector.drain()


class TestOtelTracingDemo:
    async def test_demo_runs_and_reports_the_traces(self, capsys):
        await demo._run()
        out = capsys.readouterr().out
        assert "✅ 10 spans exported with saga → step parentage" in out
        assert "saga.step.compensation.charge_card  [OK]" in out
        assert "saga.step.compensation.reserve_stock  [OK]" in out
        assert "saga.step.action.ship_order  [ERROR]" in out

    async def test_spans_carry_saga_attributes_and_parentage(self):
        happy, failed = await _traces()

        root = next(s for s in happy if s.parent_id is None)
        children = [s for s in happy if s.parent_id == root.span_id]
        assert root.attributes["saga.name"] == "order-checkout"
        assert root.attributes["saga.service"] == "test-service"
        assert [c.attributes["saga.step.name"] for c in children] == [
            "reserve_stock",
            "charge_card",
            "ship_order",
        ]
        assert {c.attributes["saga.id"] for c in children} == {root.attributes["saga.id"]}
        assert demo.verify(happy, failed) == []

    async def test_drain_empties_the_collector(self):
        collector = demo.InMemoryCollector("svc")
        saga_cls = demo.build_order_saga(demo.TracingSagaListener(tracer=collector.tracer))
        await demo.run_checkout(saga_cls, "o-3", carrier="up")
        assert collector.drain()
        assert collector.drain() == []

    def test_verify_flags_missing_or_malformed_traces(self):
        assert demo.verify([], []) == [
            "successful run has no OK saga span",
            "failing step span is not marked ERROR",
            "compensation of charge_card was not traced",
            "compensation of reserve_stock was not traced",
            "failed saga span is not marked rolled_back",
        ]

    def test_verify_flags_wrong_step_count(self):
        happy = [_span("saga", span_id=1), _span("step", span_id=2, parent_id=1)]
        failed = [
            _span("saga", span_id=1, **{"saga.status": "rolled_back"}),
            _span("saga.step.action.ship_order", span_id=2, parent_id=1, status="ERROR"),
            _span("saga.step.compensation.charge_card", span_id=3, parent_id=1),
            _span("saga.step.compensation.reserve_stock", span_id=4, parent_id=1),
        ]
        assert demo.verify(happy, failed) == [
            "successful run should have three step spans under the saga span"
        ]

    async def test_run_fails_loudly_when_verification_fails(self, monkeypatch, capsys):
        monkeypatch.setattr(demo, "verify", lambda happy, failed: ["boom"])
        with pytest.raises(RuntimeError, match="expected shape"):
            await demo._run()
        assert "❌ boom" in capsys.readouterr().out

    async def test_without_opentelemetry_the_demo_explains_how_to_install(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(demo, "is_tracing_available", lambda: False)
        await demo._run()
        assert "pip install 'sagaz[tracing]'" in capsys.readouterr().out
