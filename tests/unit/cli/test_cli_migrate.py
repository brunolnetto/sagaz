import pytest
from click.testing import CliRunner
from unittest.mock import AsyncMock, MagicMock, patch

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
    stats = MagicMock(total_records=7)
    manager.saga.get_statistics = AsyncMock(return_value=stats)
    manager.outbox.count = AsyncMock(return_value=11)

    with patch("sagaz.cli.migrate.create_storage_manager", return_value=manager):
        result = runner.invoke(migrate_cmd, ["status", "--source", "memory://"])

    assert result.exit_code == 0
    assert "Fetching record counts" in result.output
    assert "sagas=7" in result.output
    assert "outbox_events=11" in result.output
