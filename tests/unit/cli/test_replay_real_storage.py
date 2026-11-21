"""`sagaz replay` reads the snapshots a saga wrote, from another process (#556)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from click.testing import CliRunner

from sagaz.cli.app import cli
from sagaz.core.replay import ReplayConfig, SnapshotStrategy
from sagaz.core.saga import Saga as LegacySaga
from sagaz.core.storage.backends.filesystem_snapshot import FilesystemSnapshotStorage

REPLAYED: list[str] = []


async def _reserve(ctx):
    return {"reserved": True}


async def _charge(ctx):
    REPLAYED.append("charge")
    return {"charged": ctx.get("amount", 0)}


async def make_order_saga(name: str) -> LegacySaga:
    """The factory `--saga tests.unit.cli.test_replay_real_storage:make_order_saga` loads."""
    saga = LegacySaga(name)
    await saga.add_step("reserve", _reserve)
    await saga.add_step("charge", _charge)
    return saga


def record_run(directory) -> str:
    async def run() -> str:
        storage = FilesystemSnapshotStorage(base_path=str(directory))
        saga = LegacySaga(
            "order",
            replay_config=ReplayConfig(
                enable_snapshots=True, snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP
            ),
            snapshot_storage=storage,
        )
        saga.context.set("amount", 40)
        await saga.add_step("reserve", _reserve)
        await saga.add_step("charge", _charge)
        await saga.execute()
        return saga.saga_id

    return asyncio.run(run())


def invoke(*args):
    return CliRunner().invoke(cli, ["replay", *args])


def test_list_changes_and_time_travel_read_the_saga_s_snapshots(tmp_path):
    saga_id = record_run(tmp_path)
    changes = invoke(
        "list-changes", saga_id, "--storage", "filesystem", "--storage-url", str(tmp_path)
    )
    assert changes.exit_code == 0, changes.output
    assert "No state changes found" not in changes.output
    now = datetime.now(UTC).isoformat()
    state = invoke(
        "time-travel", saga_id, "--at", now, "--storage-url", str(tmp_path), "--format", "json"
    )
    assert state.exit_code == 0, state.output
    assert "No state found" not in state.output


def test_replay_runs_the_saga_again_from_a_checkpoint(tmp_path):
    saga_id = record_run(tmp_path)
    REPLAYED.clear()
    result = invoke(
        "run",
        saga_id,
        "--from-step",
        "charge",
        "--storage",
        "filesystem",
        "--storage-url",
        str(tmp_path),
        "--saga",
        "tests.unit.cli.test_replay_real_storage:make_order_saga",
    )
    assert result.exit_code == 0, result.output
    assert REPLAYED == ["charge"]  # resumed at charge: reserve was not run again


def test_a_dry_run_needs_no_saga(tmp_path):
    saga_id = record_run(tmp_path)
    args = ["run", saga_id, "--from-step", "charge", "--storage-url", str(tmp_path), "--dry-run"]
    assert invoke(*args).exit_code == 0


def test_errors_exit_non_zero(tmp_path):
    saga_id = record_run(tmp_path)
    memory = invoke("list-changes", saga_id, "--storage", "memory")
    assert memory.exit_code != 0
    assert "in-memory snapshots live in the process" in " ".join(memory.output.split())
    no_saga = invoke("run", saga_id, "--from-step", "charge", "--storage-url", str(tmp_path))
    assert no_saga.exit_code != 0
    assert "--saga" in no_saga.output
    no_url = invoke("list-changes", saga_id, "--storage", "redis")
    assert no_url.exit_code != 0
    assert "needs --storage-url" in no_url.output
    bad_id = invoke("list-changes", "not-a-uuid")
    assert bad_id.exit_code != 0
