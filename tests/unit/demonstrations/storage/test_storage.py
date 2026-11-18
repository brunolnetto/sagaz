"""Tests for storage demonstrations."""

from __future__ import annotations

import time

import pytest

from sagaz.core.storage.event_store import InMemoryEventStore
from sagaz.demonstrations.storage.event_sourcing import main as demo


async def _executed() -> demo.Demo:
    state = demo.Demo()
    await demo.execute(state)
    return state


class TestEventSourcingDemo:
    async def test_runs_fast_and_reports_history(self, capsys):
        started = time.perf_counter()
        await demo._run()
        assert time.perf_counter() - started < 0.5

        out = capsys.readouterr().out
        assert "order-1001: completed" in out
        assert "order-1002: rolled back (card declined)" in out
        assert "StepCompensated" in out
        assert "order-1002 as of event 2: executing, reserve_stock completed" in out
        assert "✅" in out

    async def test_guarantees_hold(self):
        state = await _executed()
        assert await demo.verify(state) == []
        events = await state.store.load_stream(demo.DECLINED_ORDER)
        assert [e.event_type for e in events][-3:] == [
            "CompensationStarted",
            "StepCompensated",
            "SagaRolledBack",
        ]

    async def test_verify_flags_an_empty_store(self):
        problems = await demo.verify(demo.Demo(store=InMemoryEventStore()))  # nothing ran
        assert "order-1001: no snapshot was taken" in problems
        assert "order-1001: expected completed" in problems

    async def test_verify_detects_a_broken_stream(self, monkeypatch):
        state = await _executed()
        original = state.store.load_stream

        async def shuffled(saga_id):
            events = await original(saga_id)
            return [*events[1:], events[0], events[0]]

        monkeypatch.setattr(state.store, "load_stream", shuffled)
        problems = await demo.verify(state)
        assert "order-1001: sequences are not 1..n" in problems
        assert "order-1001: duplicate event ids" in problems
        assert "order-1002: the mid-run state was not executing" in problems

    async def test_run_fails_loudly_when_a_guarantee_breaks(self, monkeypatch, capsys):
        async def broken(_):
            return ["something broke"]

        monkeypatch.setattr(demo, "verify", broken)
        with pytest.raises(RuntimeError, match="did not hold"):
            await demo._run()
        assert "❌ something broke" in capsys.readouterr().out
