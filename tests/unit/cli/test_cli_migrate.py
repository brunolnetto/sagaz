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
    result = runner.invoke(
        migrate_cmd, ["run", "--source", "memory://", "--target", "redis://localhost"]
    )
    assert result.exit_code == 0
    assert "Starting migration" in result.output
    assert "Migration complete." in result.output


def test_migrate_status(runner):
    result = runner.invoke(migrate_cmd, ["status", "--source", "memory://"])
    assert result.exit_code == 0
    assert "Fetching record counts" in result.output
