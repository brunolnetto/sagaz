#!/usr/bin/env python3
"""
OpenTelemetry Tracing — follow a saga through its spans

Attaches :class:`sagaz.core.listeners.TracingSagaListener` to an order saga
and runs it twice:

  1. a successful checkout   → one saga span with a child span per step
  2. the carrier is down     → the failing step and the saga span are ERROR,
                               and each compensation gets its own child span

Spans go to an in-memory exporter that stands in for an OTLP collector, so
no infrastructure is needed. In production, swap the exporter for
``OTLPSpanExporter`` (``pip install sagaz[tracing]``) and point it at your
collector.

Usage:
    sagaz demo run otel_tracing
    python -m sagaz.demonstrations.observability.otel_tracing.main
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from sagaz import Saga, action, compensate
from sagaz.core.listeners import TracingSagaListener
from sagaz.observability.monitoring.tracing import SagaTracer, is_tracing_available


@dataclass(frozen=True)
class SpanView:
    """The parts of a finished span this demo prints and verifies."""

    name: str
    status: str
    span_id: int
    parent_id: int | None
    attributes: dict[str, Any]


class InMemoryCollector:
    """A TracerProvider wired to an in-memory exporter (the demo's 'collector')."""

    def __init__(self, service_name: str) -> None:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        self._exporter = InMemorySpanExporter()
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(SimpleSpanProcessor(self._exporter))
        # A local provider keeps the demo from replacing the global one.
        self.tracer = SagaTracer(service_name)
        self.tracer.tracer = provider.get_tracer("sagaz.demo.otel_tracing")

    def drain(self) -> list[SpanView]:
        spans = [
            SpanView(
                name=span.name,
                status=span.status.status_code.name,
                span_id=span.context.span_id,
                parent_id=span.parent.span_id if span.parent else None,
                attributes=dict(span.attributes or {}),
            )
            for span in self._exporter.get_finished_spans()
        ]
        self._exporter.clear()
        return spans


def build_order_saga(listener: TracingSagaListener) -> type[Saga]:
    """An order saga whose shipping step fails when ``ctx['carrier'] == 'down'``."""

    class OrderSaga(Saga):
        saga_name = "order-checkout"
        listeners = [listener]

        @action("reserve_stock")
        async def reserve_stock(self, ctx: dict[str, Any]) -> dict[str, Any]:
            return {"reservation_id": f"res-{ctx['order_id']}"}

        @compensate("reserve_stock")
        async def release_stock(self, ctx: dict[str, Any]) -> None:
            ctx["stock_released"] = True

        @action("charge_card", depends_on=["reserve_stock"])
        async def charge_card(self, ctx: dict[str, Any]) -> dict[str, Any]:
            return {"charge_id": f"ch-{ctx['order_id']}"}

        @compensate("charge_card")
        async def refund_card(self, ctx: dict[str, Any]) -> None:
            ctx["refunded"] = True

        @action("ship_order", depends_on=["charge_card"])
        async def ship_order(self, ctx: dict[str, Any]) -> dict[str, Any]:
            if ctx.get("carrier") == "down":
                msg = "carrier API unavailable"
                raise RuntimeError(msg)
            return {"tracking": f"trk-{ctx['order_id']}"}

    return OrderSaga


async def run_checkout(saga_cls: type[Saga], order_id: str, carrier: str) -> str:
    """Run one checkout; return the outcome instead of raising."""
    try:
        await saga_cls().run({"order_id": order_id, "carrier": carrier})
    except Exception:
        return "rolled_back"
    return "completed"


def render_trace(spans: list[SpanView]) -> list[str]:
    """Indent child spans under their saga span, in finish order."""
    lines = []
    for root in (s for s in spans if s.parent_id is None):
        lines.append(f"  {root.name}  [{root.status}]  saga.id={root.attributes['saga.id']}")
        lines.extend(
            f"    └─ {child.name}  [{child.status}]"
            for child in spans
            if child.parent_id == root.span_id
        )
    return lines


def _root(spans: list[SpanView]) -> SpanView | None:
    return next((s for s in spans if s.parent_id is None), None)


def _check_successful_run(spans: list[SpanView]) -> list[str]:
    root = _root(spans)
    if root is None or root.status != "OK":
        return ["successful run has no OK saga span"]
    if sum(1 for s in spans if s.parent_id == root.span_id) != 3:
        return ["successful run should have three step spans under the saga span"]
    return []


def _check_failed_run(spans: list[SpanView]) -> list[str]:
    problems = []
    by_name = {s.name: s for s in spans}
    failing = by_name.get("saga.step.action.ship_order")
    if failing is None or failing.status != "ERROR":
        problems.append("failing step span is not marked ERROR")
    for step in ("charge_card", "reserve_stock"):
        if f"saga.step.compensation.{step}" not in by_name:
            problems.append(f"compensation of {step} was not traced")
    root = _root(spans)
    if root is None or root.attributes.get("saga.status") != "rolled_back":
        problems.append("failed saga span is not marked rolled_back")
    return problems


def verify(happy: list[SpanView], failed: list[SpanView]) -> list[str]:
    """Return violated expectations (empty when the traces look right)."""
    return _check_successful_run(happy) + _check_failed_run(failed)


async def _run() -> None:
    if not is_tracing_available():
        print("OpenTelemetry is not installed: pip install 'sagaz[tracing]'")
        return

    # Phase 1: Setup
    collector = InMemoryCollector("order-service")
    saga_cls = build_order_saga(TracingSagaListener(tracer=collector.tracer))
    print("🔭 OTel tracing — TracingSagaListener → in-memory collector\n")

    # Phase 2: Execute
    outcome = await run_checkout(saga_cls, "o-1001", carrier="up")
    happy = collector.drain()
    print(f"▶ checkout o-1001 (carrier up): {outcome}")
    print("\n".join(render_trace(happy)))

    outcome = await run_checkout(saga_cls, "o-1002", carrier="down")
    failed = collector.drain()
    print(f"\n▶ checkout o-1002 (carrier down): {outcome}")
    print("\n".join(render_trace(failed)))

    # Phase 3: Verify
    problems = verify(happy, failed)
    print()
    if problems:
        for problem in problems:
            print(f"❌ {problem}")
        msg = "traces did not match the expected shape"
        raise RuntimeError(msg)
    print(f"✅ {len(happy) + len(failed)} spans exported with saga → step parentage")


if __name__ == "__main__":
    asyncio.run(_run())
