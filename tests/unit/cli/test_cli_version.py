"""`sagaz version` reports the installed distribution, like `sagaz --version`."""

from __future__ import annotations

from importlib import metadata

from click.testing import CliRunner

from sagaz.cli.app import cli


def test_version_reports_the_installed_distribution():
    result = CliRunner().invoke(cli, ["version"])
    assert result.exit_code == 0
    assert f"sagaz version {metadata.version('sagaz')}" in result.output
    assert "1.0.3" not in result.output


def test_version_without_installed_metadata(monkeypatch):
    def missing(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)
    result = CliRunner().invoke(cli, ["version"])
    assert "sagaz version unknown" in result.output
