"""Multi-region saga steps with data residency (ADR-034, #59)."""

from __future__ import annotations

import asyncio
import json

import pytest
from click.testing import CliRunner
from prometheus_client import REGISTRY

from sagaz import Saga, action, compensate
from sagaz.choreography import Event, EventBus
from sagaz.cli.app import cli
from sagaz.core.config import SagaConfig
from sagaz.core.regions import (
    MultiRegionCoordinator,
    Region,
    RegionalWorker,
    RegionRegistry,
    RegionUnavailableError,
    RemoteStepError,
    bus_from_url,
    publish_failover,
)
from sagaz.core.regions._config import coordinator_from_config, regions_from_config
from sagaz.core.regions._protocol import REPLY_PREFIX, REQUEST
from sagaz.core.tenant import current_tenant_id

REGIONS = [
    Region("us-east-1", "US"),
    Region("eu-west-1", "EU"),
    Region("eu-central-1", "EU", priority=1),
]


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def registry(clock=None, home="us-east-1") -> RegionRegistry:
    return RegionRegistry(REGIONS, home, stale_after=3, clock=clock or Clock())


ran: list[tuple[str, str]] = []


class Checkout(Saga):
    saga_name = "checkout"

    @action("reserve")
    async def reserve(self, ctx):
        return {"reservation": "r-1"}

    @compensate("reserve")
    async def release(self, ctx):
        ran.append(("release", "local"))

    @action("charge", depends_on=["reserve"], region="eu-west-1", timeout_seconds=1)
    async def charge(self, ctx):
        if ctx.get("decline"):
            msg = "card declined"
            raise ValueError(msg)
        if ctx.get("slow"):
            await asyncio.sleep(5)
        return {"charge": f"ch-{current_tenant_id()}"}

    @compensate("charge")
    async def refund(self, ctx):
        ran.append(("refund", ctx.get("charge", "?")))

    @action("ship", depends_on=["charge"])
    async def ship(self, ctx):
        if ctx.get("no_truck"):
            msg = "no truck"
            raise RuntimeError(msg)
        return {"shipped": True}


class World:
    """Three in-memory regions, a coordinator at home and a worker per EU region."""

    def __init__(self, home: str = "us-east-1") -> None:
        self.clock = Clock()
        self.buses = {r.name: EventBus() for r in REGIONS}
        self.registry = RegionRegistry(REGIONS, home, stale_after=3, clock=self.clock)
        self.coordinator = MultiRegionCoordinator(self.registry, self.buses)
        self.workers = {
            name: RegionalWorker(name, self.buses[name], heartbeat_interval=60)
            for name in ("eu-west-1", "eu-central-1")
        }
        for worker in self.workers.values():
            worker.serve(Checkout)
        self.config = SagaConfig(regions=self.coordinator, metrics=False, logging=False)

    async def __aenter__(self) -> World:
        ran.clear()
        await self.coordinator.start()
        for worker in self.workers.values():
            await worker.start()
        return self

    async def __aexit__(self, *exc) -> None:
        for worker in self.workers.values():
            await worker.stop()
        await self.coordinator.stop()

    def silence(self, region: str) -> None:
        """*region* stops sending heartbeats; time passes beyond stale_after."""
        self.clock.now += 4
        for name in self.workers:
            if name != region:
                self.registry.heartbeat(name)
        self.registry.heartbeat("us-east-1")

    async def run(self, **ctx):
        return await Checkout(config=self.config).run(dict(ctx))


def failovers(source, target, reason):
    return (
        REGISTRY.get_sample_value(
            "sagaz_region_failover_total",
            {"from_region": source, "to_region": target, "reason": reason},
        )
        or 0.0
    )


class TestRegistry:
    def test_routing_and_failover_stay_in_the_jurisdiction(self):
        clock = Clock()
        regions = registry(clock)
        assert regions.home == "us-east-1"
        assert regions.route("eu-west-1") == "eu-west-1"
        clock.now = 4
        regions.heartbeat("eu-central-1")
        assert not regions.is_healthy("eu-west-1")
        assert regions.route("eu-west-1") == "eu-central-1"
        with pytest.raises(RegionUnavailableError, match="no healthy region of its jurisdiction"):
            regions.route("us-east-1")  # no other US region
        assert regions.serves("eu-central-1", "eu-west-1")
        assert not regions.serves("us-east-1", "eu-west-1")
        assert [r.name for r in regions] == ["eu-west-1", "eu-central-1", "us-east-1"]

    def test_manual_failover(self):
        regions = registry()
        regions.failover("eu-west-1", "eu-central-1")
        assert regions.route("eu-west-1") == "eu-central-1"
        with pytest.raises(ValueError, match="outside eu-west-1's jurisdiction"):
            regions.failover("eu-west-1", "us-east-1")
        regions.failover("eu-west-1", "us-east-1", force=True)
        assert regions.overrides == {"eu-west-1": "us-east-1"}
        regions.restore("eu-west-1")
        assert regions.route("eu-west-1") == "eu-west-1"

    def test_unknown_regions(self):
        with pytest.raises(ValueError, match="Home region"):
            RegionRegistry(REGIONS, "mars-1")
        with pytest.raises(ValueError, match="Unknown region"):
            registry().get("mars-1")
        regions = registry()
        regions.heartbeat("mars-1")  # ignored
        assert regions.seconds_since_heartbeat("eu-west-1") == 0


class TestSagas:
    async def test_a_step_runs_in_its_region(self):
        async with World() as world:
            calls = []
            original = world.workers["eu-west-1"]._steps[("checkout", "charge", "action")]

            async def spy(ctx):
                calls.append(dict(ctx))
                return await original(ctx)

            world.workers["eu-west-1"]._steps[("checkout", "charge", "action")] = spy
            result = await world.run(order="o-1")
        assert result["charge"] == "ch-default"
        assert calls[0]["reservation"] == "r-1"  # the worker got the context so far

    async def test_tenant_travels_with_the_request(self):
        async with World() as world:
            result = await Checkout(config=world.config).run({}, tenant_context="acme")
        assert result["charge"] == "ch-acme"

    async def test_a_remote_failure_compensates(self):
        async with World() as world:
            with pytest.raises(RemoteStepError, match="ValueError in region eu-west-1: card"):
                await world.run(decline=True)
        assert ran == [("release", "local")]  # charge never completed: nothing to refund

    async def test_compensation_runs_in_the_steps_region(self):
        async with World() as world:
            with pytest.raises(RuntimeError, match="no truck"):
                await world.run(no_truck=True)
        assert ("refund", "ch-default") in ran
        assert ran[-1] == ("release", "local")

    async def test_failover_to_a_healthy_region_of_the_jurisdiction(self):
        async with World() as world:
            before = failovers("eu-west-1", "eu-central-1", "automatic")
            world.silence("eu-west-1")
            served = []
            original = world.workers["eu-central-1"]._steps[("checkout", "charge", "action")]

            async def spy(ctx):
                served.append("eu-central-1")
                return await original(ctx)

            world.workers["eu-central-1"]._steps[("checkout", "charge", "action")] = spy
            await world.run()
            await world.run()
            assert served == ["eu-central-1", "eu-central-1"]
            assert failovers("eu-west-1", "eu-central-1", "automatic") == before + 1

            world.registry.heartbeat("eu-west-1")  # back up
            await world.run()
            assert world.coordinator.target("eu-west-1") == "eu-west-1"

    async def test_no_healthy_region_in_the_jurisdiction_fails_the_step(self):
        async with World() as world:
            world.clock.now += 4  # every region silent
            world.registry.heartbeat("us-east-1")
            with pytest.raises(RegionUnavailableError):
                await world.run()
        assert ran == [("release", "local")]

    async def test_a_slow_region_times_out_like_a_local_step(self):
        async with World() as world:
            with pytest.raises(TimeoutError):
                await world.run(slow=True)
            assert world.coordinator._pending == {}

    async def test_a_failover_to_home_runs_locally(self):
        async with World(home="eu-central-1") as world:
            world.silence("eu-west-1")
            for worker in world.workers.values():
                await worker.stop()
            result = await world.run()
        assert result["charge"] == "ch-default"

    async def test_regions_must_be_configured(self):
        with pytest.raises(ValueError, match="no coordinator: charge \\(eu-west-1\\)"):
            await Checkout(config=SagaConfig(metrics=False, logging=False)).run({})

        class Mars(Saga):
            @action("land", region="mars-1")
            async def land(self, ctx):
                return None

        async with World() as world:
            with pytest.raises(ValueError, match="Unknown region 'mars-1'"):
                await Mars(config=world.config).run({})

    async def test_imperative_steps_take_a_region(self):
        async with World() as world:
            saga = Saga(name="adhoc", config=world.config)

            async def act(ctx):
                return {"where": "remote"}

            saga.add_step("remote", act, region="eu-west-1")
            world.workers["eu-west-1"].register("adhoc", "remote", act)
            assert (await saga.run({}))["where"] == "remote"


class TestWorker:
    async def test_requests_for_unknown_steps_or_other_regions(self):
        bus = EventBus()
        worker = RegionalWorker("eu-west-1", bus, heartbeat_interval=60)
        await worker.start()
        replies = []

        async def collect(event):
            replies.append(event.data)

        bus.subscribe(REPLY_PREFIX + "c", collect)
        request = {"coordinator": "c", "saga_name": "s", "step": "x", "kind": "action"}
        await bus.publish(Event(REQUEST, {**request, "target": "eu-central-1"}))
        await bus.publish(Event(REQUEST, {**request, "target": "eu-west-1"}))
        await worker.stop()
        assert len(replies) == 1
        assert replies[0]["error_type"] == "LookupError"
        assert worker.steps == []

    async def test_heartbeats_and_their_failures(self, caplog):
        class Flaky(EventBus):
            beats = 0

            async def publish(self, event):
                Flaky.beats += 1
                if Flaky.beats == 3:
                    msg = "broker hiccup"
                    raise ConnectionError(msg)
                await super().publish(event)

        worker = RegionalWorker("eu-west-1", Flaky(), heartbeat_interval=0.01)
        await worker.start()
        await asyncio.sleep(0.08)
        await worker.stop()
        assert Flaky.beats >= 4  # kept beating after the failure
        assert "Region eu-west-1: heartbeat failed" in caplog.text


class TestCoordinator:
    def test_every_region_needs_a_bus(self):
        with pytest.raises(ValueError, match="No bus for regions"):
            MultiRegionCoordinator(registry(), {"us-east-1": EventBus()})

    async def test_failover_commands_reach_every_coordinator_once(self, caplog):
        async with World() as world:
            before = failovers("eu-west-1", "eu-central-1", "manual")
            assert await publish_failover(world.buses, "eu-west-1", "eu-central-1", False) == 3
            assert world.registry.overrides == {"eu-west-1": "eu-central-1"}
            assert failovers("eu-west-1", "eu-central-1", "manual") == before + 1
            await publish_failover(world.buses, "eu-west-1", "us-east-1", False)  # not allowed
            assert "Ignoring failover command" in caplog.text
            await publish_failover(world.buses, "eu-west-1", None, False)
            assert world.registry.overrides == {}

    async def test_publish_failover_survives_a_dead_bus(self):
        class Dead(EventBus):
            async def publish(self, event):
                msg = "down"
                raise ConnectionError(msg)

        assert await publish_failover({"a": Dead(), "b": EventBus()}, "x", None, False) == 1

    async def test_stop_cancels_pending_requests(self):
        world = World()
        await world.coordinator.start()  # no workers: nobody replies
        task = asyncio.create_task(
            world.coordinator.run(
                "eu-west-1", saga_name="s", saga_id="1", step="x", kind="action", context={}
            )
        )
        await asyncio.sleep(0)
        await world.coordinator.stop()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_buses_from_urls(self, monkeypatch):
        started = []

        async def fake_start(self):
            started.append(self)

        monkeypatch.setattr(EventBus, "start", fake_start)
        coordinator = MultiRegionCoordinator.from_regions(REGIONS, "us-east-1")
        await coordinator.start()
        await coordinator.start()  # idempotent
        assert len(started) == 3
        await coordinator.stop()


class TestBusesAndConfig:
    def test_bus_urls(self):
        assert isinstance(bus_from_url("memory://", "g", "m"), EventBus)
        redis = bus_from_url("redis://h:6379/0", "g", "m")
        assert (redis._config.consumer_group, redis._config.stream_name) == ("g", "sagaz.regions")
        kafka = bus_from_url("kafka://h1:9092,h2:9092", "g", "m")
        assert kafka._config.bootstrap_servers == "h1:9092,h2:9092"
        rabbit = bus_from_url("amqp://guest:guest@h/", "g", "m")
        assert rabbit._config.queue_name == "sagaz.regions.g"
        with pytest.raises(ValueError, match="Unsupported region bus"):
            bus_from_url("nats://h", "g", "m")

    def test_config_block(self, tmp_path):
        block = {
            "home": "us-east-1",
            "stale_after": 5,
            "members": [
                {"name": "us-east-1", "jurisdiction": "US"},
                {"name": "eu-west-1", "jurisdiction": "EU", "bus": "memory://", "priority": 2},
            ],
        }
        coordinator = coordinator_from_config(block)
        assert coordinator.registry.stale_after == 5
        assert coordinator.registry.get("eu-west-1").priority == 2
        with pytest.raises(ValueError, match="needs 'home'"):
            coordinator_from_config({"members": block["members"]})
        with pytest.raises(ValueError, match="at least one"):
            regions_from_config({})
        with pytest.raises(ValueError, match="lacks 'jurisdiction'"):
            regions_from_config({"members": [{"name": "x"}]})

        path = tmp_path / "sagaz.yaml"
        path.write_text(
            "regions:\n  home: us-east-1\n  members:\n    - {name: us-east-1, jurisdiction: US}\n",
            encoding="utf-8",
        )
        config = SagaConfig.from_file(path)
        assert isinstance(config.regions, MultiRegionCoordinator)
        assert config.with_storage(None).regions is config.regions


class TestCli:
    @pytest.fixture
    def shared(self, monkeypatch, tmp_path):
        buses = {r.name: EventBus() for r in REGIONS}
        monkeypatch.setattr(
            "sagaz.cli.region.bus_from_url",
            lambda url, group, member: buses[url.removeprefix("memory://")],
        )
        members = "\n".join(
            f"    - {{name: {r.name}, jurisdiction: {r.jurisdiction}, bus: 'memory://{r.name}',"
            f" priority: {r.priority}}}"
            for r in REGIONS
        )
        path = tmp_path / "sagaz.yaml"
        path.write_text(f"regions:\n  home: us-east-1\n  members:\n{members}\n", encoding="utf-8")
        return buses, str(path)

    def test_list(self, shared, monkeypatch):
        buses, path = shared

        async def listen_with_a_worker(regions, seconds):
            worker = RegionalWorker("eu-west-1", buses["eu-west-1"], heartbeat_interval=0.01)
            from sagaz.cli import region as region_cli

            task = asyncio.create_task(original(regions, 0.05))
            await asyncio.sleep(0)
            await worker.start()
            rows = await task
            await worker.stop()
            return rows

        from sagaz.cli import region as region_module

        original = region_module._listen
        monkeypatch.setattr(region_module, "_listen", listen_with_a_worker)
        result = CliRunner().invoke(cli, ["region", "list", "--config", path])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0].startswith("REGION")
        assert any(line.startswith("eu-west-1") and line.endswith("up") for line in lines)
        assert any(line.startswith("us-east-1 *") and line.endswith("down") for line in lines)

        result = CliRunner().invoke(cli, ["region", "list", "--config", path, "--json"])
        assert {row["region"] for row in json.loads(result.output)} == {r.name for r in REGIONS}

    def test_list_reports_unreachable_buses(self, shared, monkeypatch):
        _, path = shared

        class Dead(EventBus):
            async def start(self):
                msg = "connection refused"
                raise ConnectionError(msg)

        monkeypatch.setattr("sagaz.cli.region.bus_from_url", lambda *a: Dead())
        result = CliRunner().invoke(cli, ["region", "list", "--config", path, "--listen", "0"])
        assert "unreachable (connection refused)" in result.output

    def test_failover(self, shared):
        buses, path = shared
        commands = []

        async def collect(event):
            commands.append(event.data)

        buses["eu-west-1"].subscribe("sagaz.region.failover", collect)
        args = ["region", "failover", "--config", path, "--from", "eu-west-1"]
        result = CliRunner().invoke(cli, [*args, "--to", "eu-central-1", "--yes"])
        assert result.exit_code == 0, result.output
        assert "Sent to 3 region bus(es)" in result.output
        assert commands == [{"from": "eu-west-1", "to": "eu-central-1", "force": False}]

        refused = CliRunner().invoke(cli, [*args, "--to", "us-east-1", "--yes"])
        assert refused.exit_code == 1
        assert "outside eu-west-1's jurisdiction" in refused.output
        assert CliRunner().invoke(cli, [*args, "--to", "us-east-1"], input="n\n").exit_code == 1
        assert CliRunner().invoke(cli, args).exit_code == 1  # neither --to nor --restore
        restore = CliRunner().invoke(cli, [*args, "--restore", "--yes"])
        assert "send steps back to eu-west-1" in restore.output

    def test_failover_with_no_reachable_bus(self, shared, monkeypatch):
        _, path = shared

        class Dead(EventBus):
            async def start(self):
                msg = "down"
                raise ConnectionError(msg)

        monkeypatch.setattr("sagaz.cli.region.bus_from_url", lambda *a: Dead())
        args = ["region", "failover", "--config", path, "--from", "eu-west-1", "--restore"]
        result = CliRunner().invoke(cli, [*args, "--yes"])
        assert result.exit_code == 1
        assert "No region bus accepted" in result.output

    def test_config_errors(self, tmp_path):
        missing = CliRunner().invoke(cli, ["region", "list", "--config", str(tmp_path / "x")])
        assert "not found" in missing.output
        empty = tmp_path / "sagaz.yaml"
        empty.write_text("storage: {}\n", encoding="utf-8")
        assert (
            "no regions: block"
            in CliRunner().invoke(cli, ["region", "list", "--config", str(empty)]).output
        )
        empty.write_text("regions: {home: x, members: [{name: x}]}\n", encoding="utf-8")
        assert (
            "lacks 'jurisdiction'"
            in CliRunner().invoke(cli, ["region", "list", "--config", str(empty)]).output
        )
