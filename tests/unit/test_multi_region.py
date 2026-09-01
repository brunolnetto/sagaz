"""
Unit tests for PR #72 — multi-region coordination:
  - sagaz/core/regions.py  (Region, RegionRegistry)
  - sagaz/core/coordinator.py (VectorClock, ConflictResolution, MultiRegionCoordinator)
  - sagaz/cli/app.py  (region list, region failover commands)
"""

from __future__ import annotations

import asyncio

import pytest
from click.testing import CliRunner

from sagaz.core.coordinator import (
    ConflictPolicy,
    MultiRegionCoordinator,
    VectorClock,
    resolve_conflict,
)
from sagaz.core.regions import Region, RegionHealth, RegionRegistry

# ---------------------------------------------------------------------------
# Region / RegionRegistry
# ---------------------------------------------------------------------------


class TestRegion:
    def test_defaults(self):
        r = Region("us-east-1")
        assert r.name == "us-east-1"
        assert r.health == RegionHealth.UNKNOWN
        assert r.latency_ms == float("inf")

    def test_to_dict(self):
        r = Region("eu-west-1", priority=1)
        d = r.to_dict()
        assert d["name"] == "eu-west-1"
        assert d["priority"] == 1
        assert d["health"] == "unknown"

    def test_equality_by_name(self):
        a = Region("ap-southeast-1")
        b = Region("ap-southeast-1", priority=99)
        assert a == b

    def test_hash_by_name(self):
        r = Region("us-west-2")
        assert hash(r) == hash("us-west-2")


class TestRegionRegistry:
    def test_register_and_get(self):
        registry = RegionRegistry()
        r = Region("us-east-1")
        registry.register(r)
        assert registry.get("us-east-1") is r

    def test_first_registered_is_home(self):
        registry = RegionRegistry()
        registry.register(Region("us-east-1"))
        assert registry.home_region.name == "us-east-1"

    def test_explicit_home_flag(self):
        registry = RegionRegistry()
        registry.register(Region("us-east-1"), home=False)
        registry.register(Region("eu-west-1"), home=True)
        assert registry.home_region.name == "eu-west-1"

    def test_healthy_regions_filters(self):
        registry = RegionRegistry()
        r1 = Region("us-east-1")
        r2 = Region("eu-west-1")
        registry.register(r1)
        registry.register(r2)
        registry.update_health("us-east-1", RegionHealth.HEALTHY)
        healthy = registry.healthy_regions()
        assert len(healthy) == 1
        assert healthy[0].name == "us-east-1"

    def test_best_failover_excludes_source(self):
        registry = RegionRegistry()
        registry.register(Region("us-east-1", priority=0), home=True)
        registry.register(Region("eu-west-1", priority=1))
        registry.update_health("us-east-1", RegionHealth.HEALTHY)
        registry.update_health("eu-west-1", RegionHealth.HEALTHY)
        best = registry.best_failover(exclude="us-east-1")
        assert best.name == "eu-west-1"

    def test_best_failover_none_when_no_healthy(self):
        registry = RegionRegistry()
        registry.register(Region("us-east-1"))
        assert registry.best_failover(exclude="us-east-1") is None

    def test_update_health_updates_latency(self):
        registry = RegionRegistry()
        registry.register(Region("us-east-1"))
        registry.update_health("us-east-1", RegionHealth.HEALTHY, latency_ms=12.5)
        r = registry.get("us-east-1")
        assert r.health == RegionHealth.HEALTHY
        assert r.latency_ms == 12.5
        assert r.last_checked is not None


# ---------------------------------------------------------------------------
# VectorClock
# ---------------------------------------------------------------------------


class TestVectorClock:
    def test_tick_increments(self):
        vc = VectorClock()
        snap = vc.tick("us-east-1")
        assert snap["us-east-1"] == 1

    def test_merge_takes_max(self):
        vc = VectorClock()
        vc.tick("us-east-1")
        vc.merge({"us-east-1": 5, "eu-west-1": 2})
        assert vc.snapshot()["us-east-1"] == 5
        assert vc.snapshot()["eu-west-1"] == 2

    def test_happens_before(self):
        vc = VectorClock()
        a = {"r1": 1, "r2": 0}
        b = {"r1": 2, "r2": 1}
        assert vc.happens_before(a, b)
        assert not vc.happens_before(b, a)

    def test_happens_before_concurrent(self):
        vc = VectorClock()
        a = {"r1": 2, "r2": 0}
        b = {"r1": 0, "r2": 2}
        assert not vc.happens_before(a, b)
        assert not vc.happens_before(b, a)


# ---------------------------------------------------------------------------
# Conflict resolution
# ---------------------------------------------------------------------------


class TestConflictResolution:
    def test_last_writer_wins_selects_later(self):
        ts_a = {"r1": 1}
        ts_b = {"r1": 2}
        result = resolve_conflict("s1", "r1", ts_a, "r2", ts_b, ConflictPolicy.LAST_WRITER_WINS)
        # a happens-before b → b is the later writer → LWW selects r2
        assert result.winner == "r2"

    def test_first_writer_wins_selects_earlier(self):
        ts_a = {"r1": 1}
        ts_b = {"r1": 2}
        result = resolve_conflict("s1", "r1", ts_a, "r2", ts_b, ConflictPolicy.FIRST_WRITER_WINS)
        assert result.winner == "r1"  # a happens-before b → first is a

    def test_manual_raises(self):
        with pytest.raises(NotImplementedError):
            resolve_conflict("s1", "r1", {}, "r2", {}, ConflictPolicy.MANUAL)


# ---------------------------------------------------------------------------
# MultiRegionCoordinator
# ---------------------------------------------------------------------------


class TestMultiRegionCoordinator:
    def _make_registry(self) -> RegionRegistry:
        registry = RegionRegistry()
        r1 = Region("us-east-1", priority=0)
        r2 = Region("eu-west-1", priority=1)
        registry.register(r1, home=True)
        registry.register(r2)
        registry.update_health("us-east-1", RegionHealth.HEALTHY)
        registry.update_health("eu-west-1", RegionHealth.HEALTHY)
        return registry

    @pytest.mark.asyncio
    async def test_dispatch_step_home_region(self):
        registry = self._make_registry()
        coord = MultiRegionCoordinator(registry)

        async def my_action():
            return 42

        result = await coord.dispatch_step("s1", "reserve", None, my_action)
        assert result.success
        assert result.result == 42
        assert result.region == "us-east-1"

    @pytest.mark.asyncio
    async def test_dispatch_step_named_region(self):
        registry = self._make_registry()
        coord = MultiRegionCoordinator(registry)

        async def my_action():
            return "eu-result"

        result = await coord.dispatch_step("s1", "pay", "eu-west-1", my_action)
        assert result.success
        assert result.region == "eu-west-1"

    @pytest.mark.asyncio
    async def test_dispatch_step_captures_error(self):
        registry = self._make_registry()
        coord = MultiRegionCoordinator(registry)

        async def bad_action():
            msg = "payment failed"
            raise ValueError(msg)

        result = await coord.dispatch_step("s1", "pay", None, bad_action)
        assert not result.success
        assert "payment failed" in result.error

    @pytest.mark.asyncio
    async def test_dispatch_step_failover_on_unreachable(self):
        registry = self._make_registry()
        registry.update_health("us-east-1", RegionHealth.UNREACHABLE)
        coord = MultiRegionCoordinator(registry)

        async def my_action():
            return "fallback"

        result = await coord.dispatch_step("s1", "step", "us-east-1", my_action)
        assert result.success
        assert result.region == "eu-west-1"

    @pytest.mark.asyncio
    async def test_dispatch_step_no_region_available(self):
        registry = RegionRegistry()
        coord = MultiRegionCoordinator(registry)

        async def my_action():
            return 1

        result = await coord.dispatch_step("s1", "step", None, my_action)
        assert not result.success
        assert "No available region" in result.error

    @pytest.mark.asyncio
    async def test_manual_failover(self):
        registry = self._make_registry()
        coord = MultiRegionCoordinator(registry)
        new_region = await coord.failover("us-east-1", "eu-west-1")
        assert new_region is not None
        assert new_region.name == "eu-west-1"
        assert coord.failover_count == 1

    @pytest.mark.asyncio
    async def test_manual_failover_auto_select(self):
        registry = self._make_registry()
        coord = MultiRegionCoordinator(registry)
        new_region = await coord.failover("us-east-1")
        assert new_region is not None
        assert new_region.name == "eu-west-1"

    @pytest.mark.asyncio
    async def test_start_and_stop_lifecycle(self):
        registry = self._make_registry()
        coord = MultiRegionCoordinator(registry, health_check_interval=100.0)
        await coord.start()
        assert coord._running
        await coord.stop()
        assert not coord._running

    @pytest.mark.asyncio
    async def test_health_probe_marks_failed_region(self):
        registry = RegionRegistry()
        bad = Region("broken", broker_url="fail://broken")
        registry.register(bad, home=True)
        coord = MultiRegionCoordinator(registry, health_check_interval=100.0)
        await coord._probe_region(bad)
        assert bad.health == RegionHealth.UNREACHABLE

    @pytest.mark.asyncio
    async def test_health_probe_marks_good_region(self):
        registry = RegionRegistry()
        good = Region("good", broker_url="amqp://good")
        registry.register(good, home=True)
        coord = MultiRegionCoordinator(registry, health_check_interval=100.0)
        await coord._probe_region(good)
        assert good.health == RegionHealth.HEALTHY

    @pytest.mark.asyncio
    async def test_cross_region_call_counter(self):
        registry = self._make_registry()
        coord = MultiRegionCoordinator(registry)

        async def my_action():
            return True

        await coord.dispatch_step("s1", "step", "eu-west-1", my_action)
        assert coord.cross_region_calls == 1


# ---------------------------------------------------------------------------
# CLI region commands
# ---------------------------------------------------------------------------


class TestRegionCLI:
    def test_region_list_no_config(self):
        from sagaz.cli.app import region_group

        runner = CliRunner()
        result = runner.invoke(region_group, ["list"])
        assert result.exit_code == 0
        assert "No --config" in result.output

    def test_region_failover_aborted_without_yes(self):
        from sagaz.cli.app import region_group

        runner = CliRunner()
        result = runner.invoke(
            region_group,
            ["failover", "--from", "us-east-1", "--to", "eu-west-1"],
            input="n\n",
        )
        assert result.exit_code == 0
        assert "Aborted" in result.output

    def test_region_failover_with_yes_flag(self):
        from sagaz.cli.app import region_group

        runner = CliRunner()
        result = runner.invoke(
            region_group,
            ["failover", "--from", "us-east-1", "--to", "eu-west-1", "--yes"],
        )
        assert result.exit_code == 0
        assert "eu-west-1" in result.output
