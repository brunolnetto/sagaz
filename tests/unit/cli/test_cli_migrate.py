from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from sagaz.cli.migrate import migrate_cmd


@pytest.fixture
def runner():
    return CliRunner()


def test_migrate_run_dry_run(runner):
    result = runner.invoke(
        migrate_cmd, ["run", "--source", "memory://", "--target", "redis://localhost", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "[dry-run] Would migrate" in result.output


def test_migrate_run_actual(runner):
    manager = AsyncMock()
    manager.__aenter__.return_value = manager
    manager.__aexit__.return_value = None

    migration_result = MagicMock(
        success=True,
        sagas_transferred=2,
        sagas_failed=0,
        events_transferred=3,
        events_failed=0,
    )
    migrator = AsyncMock()
    migrator.migrate.return_value = migration_result
    migrator.verify.return_value = MagicMock(
        ok=True, source_sagas=2, dest_sagas=2, source_events=3, dest_events=3
    )

    with (
        patch("sagaz.cli.migrate.create_storage_manager", return_value=manager),
        patch("sagaz.cli.migrate.SagaStorageMigrator", return_value=migrator),
    ):
        result = runner.invoke(
            migrate_cmd, ["run", "--source", "memory://", "--target", "redis://localhost"]
        )
    assert result.exit_code == 0
    assert "Starting migration" in result.output
    assert "Migration complete." in result.output


def test_migrate_status(runner):
    manager = AsyncMock()
    manager.__aenter__.return_value = manager
    manager.__aexit__.return_value = None
    manager.saga.count = AsyncMock(return_value=7)
    manager.outbox.count = AsyncMock(return_value=11)

    with patch("sagaz.cli.migrate.create_storage_manager", return_value=manager):
        result = runner.invoke(migrate_cmd, ["status", "--source", "memory://"])

    assert result.exit_code == 0
    assert "Fetching record counts" in result.output
    assert "sagas=7" in result.output
    assert "outbox_events=11" in result.output


def _run_with(runner, *, success=True, verify_ok=True, extra_args=()):
    manager = AsyncMock()
    manager.__aenter__.return_value = manager
    manager.__aexit__.return_value = None
    migrator = AsyncMock()
    migrator.migrate.return_value = MagicMock(
        success=success,
        sagas_transferred=2,
        sagas_failed=0 if success else 1,
        events_transferred=3,
        events_failed=0,
    )
    migrator.verify.return_value = MagicMock(
        ok=verify_ok,
        source_sagas=2,
        dest_sagas=2 if verify_ok else 1,
        source_events=3,
        dest_events=3,
    )
    with (
        patch("sagaz.cli.migrate.create_storage_manager", return_value=manager),
        patch("sagaz.cli.migrate.SagaStorageMigrator", return_value=migrator),
    ):
        result = runner.invoke(
            migrate_cmd,
            ["run", "--source", "memory://", "--target", "redis://localhost", *extra_args],
        )
    return result, migrator


def test_migrate_run_validate_passes(runner):
    result, migrator = _run_with(runner, extra_args=["--validate", "--on-error", "skip"])
    assert result.exit_code == 0
    assert "Verification passed: sagas 2->2, events 3->3" in result.output
    assert "Migration complete." in result.output
    migrator.migrate.assert_awaited_once_with(dry_run=False, batch_size=100, on_error="skip")


def test_migrate_run_validate_fails(runner):
    result, _ = _run_with(runner, verify_ok=False, extra_args=["--validate"])
    assert result.exit_code == 1
    assert "Verification failed: sagas 2->1" in result.output
    assert "Migration verification failed." in result.output
    assert "Migration complete." not in result.output


def test_migrate_run_without_validate_skips_verify(runner):
    result, migrator = _run_with(runner)
    assert result.exit_code == 0
    migrator.verify.assert_not_awaited()


def test_migrate_run_with_failures_exits_nonzero(runner):
    result, _ = _run_with(runner, success=False)
    assert result.exit_code == 1
    assert "sagas=2 (failed=1)" in result.output
    assert "Migration completed with failures." in result.output
