"""Tests for the visualization and Grafana monitor CLI command."""

from __future__ import annotations

import re
from unittest.mock import patch

from click.testing import CliRunner

from sagaz.cli.app import cli, monitor_cmd


def test_monitor_defaults_to_web_dashboard(monkeypatch):
    monkeypatch.delenv("SAGAZ_VISUALIZATION_TOKEN", raising=False)
    monkeypatch.delenv("SAGAZ_STORAGE_URL", raising=False)
    runner = CliRunner()

    with (
        patch("webbrowser.open") as open_browser,
        patch("sagaz.visualization.server.run_server") as run_server,
    ):
        result = runner.invoke(monitor_cmd, [])

    assert result.exit_code == 0, result.output
    assert "http://127.0.0.1:7070/" in result.output
    open_browser.assert_called_once_with("http://127.0.0.1:7070/")

    match = re.search(r"SAGAZ_VISUALIZATION_TOKEN=([A-Za-z0-9_-]+)", result.output)
    assert match is not None
    token = match.group(1)

    run_server.assert_called_once_with(
        host="127.0.0.1",
        port=7070,
        event_token=token,
        analytics_storage_url=None,
    )


def test_monitor_uses_existing_token_and_custom_port(monkeypatch):
    monkeypatch.delenv("SAGAZ_STORAGE_URL", raising=False)
    monkeypatch.setenv("SAGAZ_VISUALIZATION_TOKEN", "existing-worker-token")

    with (
        patch("webbrowser.open") as open_browser,
        patch("sagaz.visualization.server.run_server") as run_server,
    ):
        result = CliRunner().invoke(
            monitor_cmd,
            ["--host", "0.0.0.0", "--port", "8123", "--no-browser", "--unsafe-expose"],
        )

    assert result.exit_code == 0, result.output
    assert "http://127.0.0.1:8123/" in result.output
    assert "already configured" in result.output
    assert "existing-worker-token" not in result.output

    open_browser.assert_not_called()
    run_server.assert_called_once_with(
        host="0.0.0.0",
        port=8123,
        event_token="existing-worker-token",
        analytics_storage_url=None,
    )


def test_monitor_grafana_preserves_previous_behavior():
    with (
        patch("webbrowser.open") as open_browser,
        patch("sagaz.visualization.server.run_server") as run_server,
    ):
        result = CliRunner().invoke(monitor_cmd, ["--ui", "grafana"])

    assert result.exit_code == 0, result.output
    assert "http://localhost:3000" in result.output
    open_browser.assert_called_once_with("http://localhost:3000")
    run_server.assert_not_called()


def test_monitor_grafana_no_browser():
    with patch("webbrowser.open") as open_browser:
        result = CliRunner().invoke(
            monitor_cmd,
            ["--ui", "grafana", "--no-browser"],
        )

    assert result.exit_code == 0
    assert "http://localhost:3000" in result.output
    open_browser.assert_not_called()


def test_monitor_rejects_invalid_port():
    with patch("sagaz.visualization.server.run_server") as run_server:
        result = CliRunner().invoke(monitor_cmd, ["--port", "70000"])

    assert result.exit_code == 2
    run_server.assert_not_called()


def test_monitor_is_registered_on_main_cli():
    result = CliRunner().invoke(cli, ["monitor", "--help"])

    assert result.exit_code == 0
    assert "--ui" in result.output
    assert "--port" in result.output
    assert "--no-browser" in result.output
    assert "--unsafe-expose" in result.output
    assert "--advertise-host" in result.output


def test_monitor_nonloopback_without_unsafe_expose_fails():
    """Binding beyond loopback without --unsafe-expose must exit with code 2."""
    with patch("sagaz.visualization.server.run_server") as run_server:
        result = CliRunner().invoke(monitor_cmd, ["--host", "0.0.0.0"])

    assert result.exit_code == 2
    assert "unsafe-expose" in result.output
    run_server.assert_not_called()


def test_monitor_nonloopback_with_unsafe_expose_warns(monkeypatch):
    """With --unsafe-expose, non-loopback binding must warn about unauthenticated read endpoints."""
    monkeypatch.delenv("SAGAZ_VISUALIZATION_TOKEN", raising=False)

    with (
        patch("webbrowser.open"),
        patch("sagaz.visualization.server.run_server"),
    ):
        result = CliRunner().invoke(
            monitor_cmd,
            ["--host", "0.0.0.0", "--unsafe-expose", "--no-browser"],
        )

    assert result.exit_code == 0, result.output
    assert "unauthenticated" in result.output.lower()


def test_monitor_loopback_does_not_require_unsafe_expose():
    """Loopback binding (127.0.0.1) must not require --unsafe-expose."""
    with (
        patch("webbrowser.open"),
        patch("sagaz.visualization.server.run_server"),
    ):
        result = CliRunner().invoke(monitor_cmd, ["--no-browser"])

    assert result.exit_code == 0, result.output
    assert "unsafe-expose" not in result.output


def test_monitor_advertise_host_overrides_worker_url(monkeypatch):
    """--advertise-host must replace the default 127.0.0.1 in the worker export URL."""
    monkeypatch.delenv("SAGAZ_VISUALIZATION_TOKEN", raising=False)

    with (
        patch("webbrowser.open"),
        patch("sagaz.visualization.server.run_server"),
    ):
        result = CliRunner().invoke(
            monitor_cmd,
            [
                "--host",
                "0.0.0.0",
                "--port",
                "7070",
                "--advertise-host",
                "192.168.1.5",
                "--unsafe-expose",
                "--no-browser",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "SAGAZ_VISUALIZATION_URL=http://192.168.1.5:7070" in result.output


def test_monitor_wildcard_binding_prints_advertise_host_note(monkeypatch):
    """Wildcard binding without --advertise-host must note that workers on other hosts need it."""
    monkeypatch.delenv("SAGAZ_VISUALIZATION_TOKEN", raising=False)

    with (
        patch("webbrowser.open"),
        patch("sagaz.visualization.server.run_server"),
    ):
        result = CliRunner().invoke(
            monitor_cmd,
            ["--host", "0.0.0.0", "--unsafe-expose", "--no-browser"],
        )

    assert result.exit_code == 0, result.output
    assert "--advertise-host" in result.output


def test_monitor_passes_storage_url_for_analytics(monkeypatch):
    monkeypatch.delenv("SAGAZ_STORAGE_URL", raising=False)
    with patch("sagaz.visualization.server.run_server") as run_server:
        result = CliRunner().invoke(
            monitor_cmd, ["--no-browser", "--storage-url", "sqlite:///sagas.db"]
        )

    assert result.exit_code == 0, result.output
    assert run_server.call_args.kwargs["analytics_storage_url"] == "sqlite:///sagas.db"


def test_monitor_reads_storage_url_from_environment(monkeypatch):
    monkeypatch.setenv("SAGAZ_STORAGE_URL", "postgresql://u@db/sagas")
    with patch("sagaz.visualization.server.run_server") as run_server:
        result = CliRunner().invoke(monitor_cmd, ["--no-browser"])

    assert result.exit_code == 0, result.output
    assert run_server.call_args.kwargs["analytics_storage_url"] == "postgresql://u@db/sagas"
