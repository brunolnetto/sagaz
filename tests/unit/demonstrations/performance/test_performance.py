"""Tests for the optimization_guide demonstration.

Timing-sensitive thresholds are checked with synthetic measurements; the real
experiments are only required to complete and to point in the right direction,
so a loaded machine cannot make these tests flaky.
"""

from __future__ import annotations

import pytest

from sagaz.core.types import SagaStatus
from sagaz.demonstrations.performance.optimization_guide import main as demo


def _comparison(baseline_ms, optimized_ms, *, completed=True):
    return demo.Comparison("exp", "base", baseline_ms, "opt", optimized_ms, completed)


FAST_STORAGE = {"in-memory": 1.0, "sqlite": 5.0, "redis (simulated RTT)": 10.0}


class TestExperiments:
    async def test_parallel_dag_completes_and_beats_sequential(self):
        result = await demo.parallelism_experiment()
        assert result.all_completed
        assert result.speedup > 1

    async def test_both_variants_complete_the_saga(self):
        assert await demo._run_checkout(parallel=True) == SagaStatus.COMPLETED
        assert await demo._run_checkout(parallel=False) == SagaStatus.COMPLETED

    async def test_storage_backends_are_all_measured(self):
        timings = await demo.storage_experiment()
        assert set(timings) == {"in-memory", "sqlite", "redis (simulated RTT)"}
        assert all(ms > 0 for ms in timings.values())

    async def test_simulated_redis_round_trips_state(self):
        storage = demo.SimulatedRedisSagaStorage()
        await storage.save_saga_state("s1", "Checkout", SagaStatus.COMPLETED, [], {"a": 1})
        loaded = await storage.load_saga_state("s1")
        assert loaded["context"] == {"a": 1}

    async def test_backoff_recovers_from_transient_failures(self):
        result = await demo.backoff_experiment()
        assert result.all_completed
        assert result.speedup > 1

    async def test_flaky_step_fails_then_succeeds(self):
        step = demo._flaky(failures=1)
        with pytest.raises(ConnectionError):
            await step({})
        assert await step({}) == {"attempts": 2}


class TestVerify:
    def test_accepts_measurements_that_support_the_guide(self):
        assert demo.verify(_comparison(40, 10), FAST_STORAGE, _comparison(60, 12)) == []

    def test_flags_every_unsupported_recommendation(self):
        problems = demo.verify(
            _comparison(10, 10, completed=False),
            {"in-memory": 9.0, "sqlite": 1.0, "redis (simulated RTT)": 2.0},
            _comparison(10, 9, completed=False),
        )
        assert problems == [
            "a saga in 'exp' did not complete",
            "a saga in 'exp' did not complete",
            "parallel DAG was not at least 1.5x faster than sequential",
            "in-memory storage was not faster than a networked backend",
            "aggressive backoff did not recover at least 1.5x sooner",
        ]

    def test_zero_optimized_time_counts_as_infinite_speedup(self):
        assert _comparison(5, 0).speedup == float("inf")


class TestGuide:
    async def test_prints_measurements_and_recommendations(self, monkeypatch, capsys):
        monkeypatch.setattr(demo, "verify", lambda *measurements: [])
        await demo._run()
        out = capsys.readouterr().out
        assert "parallel DAG" in out
        assert "redis (simulated RTT)" in out
        assert "✅ Recommendations hold on this machine:" in out

    async def test_fails_loudly_when_measurements_disagree(self, monkeypatch, capsys):
        monkeypatch.setattr(demo, "verify", lambda *measurements: ["boom"])
        with pytest.raises(RuntimeError, match="did not support"):
            await demo._run()
        assert "❌ boom" in capsys.readouterr().out
