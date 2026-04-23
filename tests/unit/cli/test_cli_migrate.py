from click.testing import CliRunner

from sagaz.cli.migrate import migrate_run, migrate_status


def test_migrate_run_dry_run():
    runner = CliRunner()
    result = runner.invoke(migrate_run, ["--source", "src", "--target", "tgt", "--dry-run"])
    assert result.exit_code == 0
    assert "[dry-run] Would migrate from src to tgt" in result.output


def test_migrate_run():
    runner = CliRunner()
    result = runner.invoke(migrate_run, ["--source", "src", "--target", "tgt"])
    assert result.exit_code == 0
    assert "Starting migration from src \u2192 tgt" in result.output


def test_migrate_status():
    runner = CliRunner()
    result = runner.invoke(migrate_status, ["--source", "src"])
    assert result.exit_code == 0
    assert "Fetching record counts from src" in result.output
