"""
Unit tests for sagaz/cli/_setup_handlers.py

Covers all public helper functions for the `sagaz setup` command wizard.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# _check_project_exists
# ---------------------------------------------------------------------------


class TestCheckProjectExists:
    def test_exists_no_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "sagaz.yaml").touch()
        from sagaz.cli._setup_handlers import _check_project_exists

        _check_project_exists()  # should not raise / exit

    def test_missing_calls_sys_exit(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from sagaz.cli._setup_handlers import _check_project_exists

        with pytest.raises(SystemExit):
            _check_project_exists()


# ---------------------------------------------------------------------------
# _display_setup_header
# ---------------------------------------------------------------------------


class TestDisplaySetupHeader:
    def test_displays_with_rich_console(self):
        from sagaz.cli._setup_handlers import _display_setup_header

        mock_console = MagicMock()
        mock_panel = MagicMock()
        mock_panel.fit.return_value = "panel"

        with (
            patch("sagaz.cli._setup_handlers.console", mock_console),
            patch("sagaz.cli._setup_handlers.Panel", mock_panel),
        ):
            _display_setup_header()
        mock_console.print.assert_called_once()

    def test_displays_without_rich_console(self):
        from sagaz.cli._setup_handlers import _display_setup_header

        with (
            patch("sagaz.cli._setup_handlers.console", None),
            patch("sagaz.cli._setup_handlers.click.echo") as mock_echo,
        ):
            _display_setup_header()
        mock_echo.assert_called()


# ---------------------------------------------------------------------------
# _prompt_deployment_mode
# ---------------------------------------------------------------------------


class TestPromptDeploymentMode:
    @pytest.mark.parametrize(
        ("choice", "expected"),
        [
            (1, "local"),
            (2, "k8s"),
            (3, "selfhost"),
            (4, "hybrid"),
        ],
    )
    def test_mode_choices(self, choice, expected):
        from sagaz.cli._setup_handlers import _prompt_deployment_mode

        with (
            patch("sagaz.cli._setup_handlers.click.prompt", return_value=choice),
            patch("sagaz.cli._setup_handlers.click.echo"),
        ):
            assert _prompt_deployment_mode() == expected


# ---------------------------------------------------------------------------
# _prompt_oltp_storage
# ---------------------------------------------------------------------------


class TestPromptOltpStorage:
    @pytest.mark.parametrize(
        ("choice", "expected"),
        [
            (1, "postgresql"),
            (2, "in-memory"),
            (3, "sqlite"),
        ],
    )
    def test_storage_choices(self, choice, expected):
        from sagaz.cli._setup_handlers import _prompt_oltp_storage

        with (
            patch("sagaz.cli._setup_handlers.click.prompt", return_value=choice),
            patch("sagaz.cli._setup_handlers.click.echo"),
            patch("sagaz.cli._setup_handlers.click.confirm", return_value=False),
        ):
            storage, with_ha = _prompt_oltp_storage("local")
        assert storage == expected
        assert with_ha is False

    def test_postgresql_ha_enabled_for_k8s(self):
        from sagaz.cli._setup_handlers import _prompt_oltp_storage

        with (
            patch("sagaz.cli._setup_handlers.click.prompt", return_value=1),
            patch("sagaz.cli._setup_handlers.click.echo"),
            patch("sagaz.cli._setup_handlers.click.confirm", return_value=True),
        ):
            storage, with_ha = _prompt_oltp_storage("k8s")
        assert storage == "postgresql"
        assert with_ha is True

    def test_postgresql_ha_enabled_for_selfhost(self):
        from sagaz.cli._setup_handlers import _prompt_oltp_storage

        with (
            patch("sagaz.cli._setup_handlers.click.prompt", return_value=1),
            patch("sagaz.cli._setup_handlers.click.echo"),
            patch("sagaz.cli._setup_handlers.click.confirm", return_value=True),
        ):
            storage, with_ha = _prompt_oltp_storage("selfhost")
        assert with_ha is True

    def test_ha_not_prompted_for_local_mode(self):
        from sagaz.cli._setup_handlers import _prompt_oltp_storage

        with (
            patch("sagaz.cli._setup_handlers.click.prompt", return_value=1),
            patch("sagaz.cli._setup_handlers.click.echo"),
            patch("sagaz.cli._setup_handlers.click.confirm") as mock_confirm,
        ):
            _, with_ha = _prompt_oltp_storage("local")
        mock_confirm.assert_not_called()
        assert with_ha is False


# ---------------------------------------------------------------------------
# _prompt_message_broker
# ---------------------------------------------------------------------------


class TestPromptMessageBroker:
    @pytest.mark.parametrize(
        ("choice", "expected"),
        [(1, "redis"), (2, "rabbitmq"), (3, "kafka")],
    )
    def test_broker_choices(self, choice, expected):
        from sagaz.cli._setup_handlers import _prompt_message_broker

        with (
            patch("sagaz.cli._setup_handlers.click.prompt", return_value=choice),
            patch("sagaz.cli._setup_handlers.click.echo"),
        ):
            assert _prompt_message_broker() == expected


# ---------------------------------------------------------------------------
# _prompt_outbox_storage
# ---------------------------------------------------------------------------


class TestPromptOutboxStorage:
    @pytest.mark.parametrize(
        ("choice", "expected_storage", "expected_separate"),
        [
            (1, "same", False),
            (2, "postgresql", True),
            (3, "in-memory", True),
        ],
    )
    def test_outbox_choices(self, choice, expected_storage, expected_separate):
        from sagaz.cli._setup_handlers import _prompt_outbox_storage

        with (
            patch("sagaz.cli._setup_handlers.click.prompt", return_value=choice),
            patch("sagaz.cli._setup_handlers.click.echo"),
        ):
            storage, separate = _prompt_outbox_storage()
        assert storage == expected_storage
        assert separate == expected_separate


# ---------------------------------------------------------------------------
# _prompt_metrics / _prompt_tracing / _prompt_logging / _prompt_benchmarks
# ---------------------------------------------------------------------------


class TestBooleanPrompts:
    @pytest.mark.parametrize(
        ("fn_name", "confirm_value"),
        [
            ("_prompt_metrics", True),
            ("_prompt_metrics", False),
            ("_prompt_tracing", True),
            ("_prompt_tracing", False),
            ("_prompt_logging", True),
            ("_prompt_logging", False),
            ("_prompt_benchmarks", True),
            ("_prompt_benchmarks", False),
        ],
    )
    def test_returns_confirm_value(self, fn_name, confirm_value):
        import sagaz.cli._setup_handlers as mod

        fn = getattr(mod, fn_name)
        with (
            patch("sagaz.cli._setup_handlers.click.confirm", return_value=confirm_value),
            patch("sagaz.cli._setup_handlers.click.echo"),
        ):
            assert fn() == confirm_value


# ---------------------------------------------------------------------------
# _determine_dev_mode
# ---------------------------------------------------------------------------


class TestDetermineDevMode:
    def test_in_memory_oltp_auto_enables_dev_mode(self):
        from sagaz.cli._setup_handlers import _determine_dev_mode

        with (
            patch("sagaz.cli._setup_handlers.click.echo"),
            patch("sagaz.cli._setup_handlers.click.confirm") as mock_confirm,
        ):
            result = _determine_dev_mode("in-memory", "same")
        assert result is True
        mock_confirm.assert_not_called()

    def test_in_memory_outbox_auto_enables_dev_mode(self):
        from sagaz.cli._setup_handlers import _determine_dev_mode

        with (
            patch("sagaz.cli._setup_handlers.click.echo"),
            patch("sagaz.cli._setup_handlers.click.confirm") as mock_confirm,
        ):
            result = _determine_dev_mode("postgresql", "in-memory")
        assert result is True
        mock_confirm.assert_not_called()

    def test_explicit_confirm_returns_user_choice_true(self):
        from sagaz.cli._setup_handlers import _determine_dev_mode

        with (
            patch("sagaz.cli._setup_handlers.click.echo"),
            patch("sagaz.cli._setup_handlers.click.confirm", return_value=True),
        ):
            assert _determine_dev_mode("postgresql", "same") is True

    def test_explicit_confirm_returns_user_choice_false(self):
        from sagaz.cli._setup_handlers import _determine_dev_mode

        with (
            patch("sagaz.cli._setup_handlers.click.echo"),
            patch("sagaz.cli._setup_handlers.click.confirm", return_value=False),
        ):
            assert _determine_dev_mode("postgresql", "same") is False


# ---------------------------------------------------------------------------
# _display_configuration_summary
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "mode": "local",
    "oltp_storage": "postgresql",
    "outbox_storage": "same",
    "broker": "redis",
    "with_ha": False,
    "with_metrics": True,
    "with_tracing": True,
    "with_logging": True,
    "with_benchmarks": False,
    "with_observability": True,
    "dev_mode": False,
}


class TestDisplayConfigurationSummary:
    def test_rich_console_path(self):
        from sagaz.cli._setup_handlers import _display_configuration_summary

        mock_console = MagicMock()
        with patch("sagaz.cli._setup_handlers.console", mock_console):
            _display_configuration_summary(_BASE_CONFIG)
        mock_console.print.assert_called_once()

    def test_no_console_path(self):
        from sagaz.cli._setup_handlers import _display_configuration_summary

        with (
            patch("sagaz.cli._setup_handlers.console", None),
            patch("sagaz.cli._setup_handlers.click.echo") as mock_echo,
        ):
            _display_configuration_summary(_BASE_CONFIG)
        mock_echo.assert_called()

    def test_postgresql_ha_storage_label(self):
        from sagaz.cli._setup_handlers import _display_configuration_summary

        config = {**_BASE_CONFIG, "with_ha": True}
        mock_console = MagicMock()
        with patch("sagaz.cli._setup_handlers.console", mock_console):
            _display_configuration_summary(config)
        output = mock_console.print.call_args[0][0]
        assert "HA" in output or "ha" in output.lower()

    def test_same_outbox_shows_oltp_in_label(self):
        from sagaz.cli._setup_handlers import _display_configuration_summary

        config = {**_BASE_CONFIG, "outbox_storage": "same"}
        mock_console = MagicMock()
        with patch("sagaz.cli._setup_handlers.console", mock_console):
            _display_configuration_summary(config)
        output = mock_console.print.call_args[0][0]
        assert "postgresql" in output.lower()

    def test_dev_mode_visible_in_output(self):
        from sagaz.cli._setup_handlers import _display_configuration_summary

        config = {**_BASE_CONFIG, "dev_mode": True}
        mock_console = MagicMock()
        with patch("sagaz.cli._setup_handlers.console", mock_console):
            _display_configuration_summary(config)
        output = mock_console.print.call_args[0][0]
        assert "Yes" in output or "yes" in output.lower()


# ---------------------------------------------------------------------------
# _execute_setup
# ---------------------------------------------------------------------------


class TestExecuteSetup:
    def _make_config(self, mode, with_benchmarks=False):
        return {
            "mode": mode,
            "broker": "redis",
            "with_observability": True,
            "with_ha": False,
            "separate_outbox": False,
            "oltp_storage": "postgresql",
            "outbox_storage": "same",
            "dev_mode": False,
            "with_benchmarks": with_benchmarks,
        }

    def test_local_mode(self):
        from sagaz.cli._setup_handlers import _execute_setup

        config = self._make_config("local")
        with (
            patch("sagaz.cli._setup_handlers._init_local") as mock_local,
            patch("sagaz.cli._setup_handlers._init_benchmarks"),
        ):
            _execute_setup(config)
        mock_local.assert_called_once_with("redis", True, False, False, "postgresql", "same", False)

    def test_selfhost_mode(self):
        from sagaz.cli._setup_handlers import _execute_setup

        config = self._make_config("selfhost")
        with (
            patch("sagaz.cli._setup_handlers._init_selfhost") as mock_sh,
            patch("sagaz.cli._setup_handlers._init_benchmarks"),
        ):
            _execute_setup(config)
        mock_sh.assert_called_once()

    def test_k8s_mode(self):
        from sagaz.cli._setup_handlers import _execute_setup

        config = self._make_config("k8s")
        with (
            patch("sagaz.cli._setup_handlers._init_k8s") as mock_k8s,
            patch("sagaz.cli._setup_handlers._init_benchmarks"),
        ):
            _execute_setup(config)
        mock_k8s.assert_called_once()

    def test_hybrid_mode(self):
        from sagaz.cli._setup_handlers import _execute_setup

        config = self._make_config("hybrid")
        with (
            patch("sagaz.cli._setup_handlers._init_hybrid") as mock_hyb,
            patch("sagaz.cli._setup_handlers._init_benchmarks"),
        ):
            _execute_setup(config)
        mock_hyb.assert_called_once_with("redis", "postgresql", "same")

    def test_benchmarks_called_for_non_k8s_mode(self):
        from sagaz.cli._setup_handlers import _execute_setup

        config = self._make_config("local", with_benchmarks=True)
        with (
            patch("sagaz.cli._setup_handlers._init_local"),
            patch("sagaz.cli._setup_handlers._init_benchmarks") as mock_bench,
        ):
            _execute_setup(config)
        mock_bench.assert_called_once()

    def test_benchmarks_not_called_for_k8s_mode(self):
        from sagaz.cli._setup_handlers import _execute_setup

        config = self._make_config("k8s", with_benchmarks=True)
        with (
            patch("sagaz.cli._setup_handlers._init_k8s"),
            patch("sagaz.cli._setup_handlers._init_benchmarks") as mock_bench,
        ):
            _execute_setup(config)
        mock_bench.assert_not_called()

    def test_no_benchmarks_when_flag_false(self):
        from sagaz.cli._setup_handlers import _execute_setup

        config = self._make_config("local", with_benchmarks=False)
        with (
            patch("sagaz.cli._setup_handlers._init_local"),
            patch("sagaz.cli._setup_handlers._init_benchmarks") as mock_bench,
        ):
            _execute_setup(config)
        mock_bench.assert_not_called()


# ---------------------------------------------------------------------------
# _gather_setup_configuration
# ---------------------------------------------------------------------------


class TestGatherSetupConfiguration:
    def test_returns_all_required_keys(self):
        from sagaz.cli._setup_handlers import _gather_setup_configuration

        with (
            patch("sagaz.cli._setup_handlers._prompt_deployment_mode", return_value="local"),
            patch(
                "sagaz.cli._setup_handlers._prompt_oltp_storage",
                return_value=("postgresql", False),
            ),
            patch("sagaz.cli._setup_handlers._prompt_message_broker", return_value="redis"),
            patch(
                "sagaz.cli._setup_handlers._prompt_outbox_storage",
                return_value=("same", False),
            ),
            patch("sagaz.cli._setup_handlers._prompt_metrics", return_value=True),
            patch("sagaz.cli._setup_handlers._prompt_tracing", return_value=True),
            patch("sagaz.cli._setup_handlers._prompt_logging", return_value=True),
            patch("sagaz.cli._setup_handlers._prompt_benchmarks", return_value=False),
            patch("sagaz.cli._setup_handlers._determine_dev_mode", return_value=False),
        ):
            config = _gather_setup_configuration()

        required_keys = {
            "mode",
            "oltp_storage",
            "with_ha",
            "broker",
            "outbox_storage",
            "separate_outbox",
            "with_metrics",
            "with_tracing",
            "with_logging",
            "with_benchmarks",
            "dev_mode",
            "with_observability",
        }
        assert required_keys.issubset(config.keys())

    def test_with_observability_true_if_any_enabled(self):
        from sagaz.cli._setup_handlers import _gather_setup_configuration

        with (
            patch("sagaz.cli._setup_handlers._prompt_deployment_mode", return_value="local"),
            patch(
                "sagaz.cli._setup_handlers._prompt_oltp_storage",
                return_value=("postgresql", False),
            ),
            patch("sagaz.cli._setup_handlers._prompt_message_broker", return_value="redis"),
            patch(
                "sagaz.cli._setup_handlers._prompt_outbox_storage",
                return_value=("same", False),
            ),
            patch("sagaz.cli._setup_handlers._prompt_metrics", return_value=True),
            patch("sagaz.cli._setup_handlers._prompt_tracing", return_value=False),
            patch("sagaz.cli._setup_handlers._prompt_logging", return_value=False),
            patch("sagaz.cli._setup_handlers._prompt_benchmarks", return_value=False),
            patch("sagaz.cli._setup_handlers._determine_dev_mode", return_value=False),
        ):
            config = _gather_setup_configuration()

        assert config["with_observability"] is True

    def test_with_observability_false_if_all_disabled(self):
        from sagaz.cli._setup_handlers import _gather_setup_configuration

        with (
            patch("sagaz.cli._setup_handlers._prompt_deployment_mode", return_value="k8s"),
            patch(
                "sagaz.cli._setup_handlers._prompt_oltp_storage",
                return_value=("postgresql", False),
            ),
            patch("sagaz.cli._setup_handlers._prompt_message_broker", return_value="kafka"),
            patch(
                "sagaz.cli._setup_handlers._prompt_outbox_storage",
                return_value=("postgresql", True),
            ),
            patch("sagaz.cli._setup_handlers._prompt_metrics", return_value=False),
            patch("sagaz.cli._setup_handlers._prompt_tracing", return_value=False),
            patch("sagaz.cli._setup_handlers._prompt_logging", return_value=False),
            patch("sagaz.cli._setup_handlers._prompt_benchmarks", return_value=False),
            patch("sagaz.cli._setup_handlers._determine_dev_mode", return_value=False),
        ):
            config = _gather_setup_configuration()

        assert config["with_observability"] is False


# ---------------------------------------------------------------------------
# Edge cases for remaining branch coverage
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_display_summary_outbox_not_same(self):
        """Covers branch 170->173: outbox_storage != 'same'."""
        from sagaz.cli._setup_handlers import _display_configuration_summary

        config = {**_BASE_CONFIG, "outbox_storage": "postgresql"}
        mock_console = MagicMock()
        with patch("sagaz.cli._setup_handlers.console", mock_console):
            _display_configuration_summary(config)
        output = mock_console.print.call_args[0][0]
        # outbox_label should be "postgresql", not "same as OLTP ..."
        assert "postgresql" in output

    def test_execute_setup_unknown_mode_still_runs_benchmarks(self):
        """Covers branch 225->228: mode not matching any elif still hits benchmark check."""
        from sagaz.cli._setup_handlers import _execute_setup

        config = {
            "mode": "unknown_mode",
            "broker": "redis",
            "with_observability": False,
            "with_ha": False,
            "separate_outbox": False,
            "oltp_storage": "postgresql",
            "outbox_storage": "same",
            "dev_mode": False,
            "with_benchmarks": True,
        }
        with (
            patch("sagaz.cli._setup_handlers._init_local") as mock_local,
            patch("sagaz.cli._setup_handlers._init_benchmarks") as mock_bench,
        ):
            _execute_setup(config)
        mock_local.assert_not_called()
        mock_bench.assert_called_once()

    def test_import_fallback_when_rich_unavailable(self):
        """Covers lines 27-29: except ImportError → console=None, Panel=None."""
        import importlib
        import sys

        # Remove cached module so we can re-import with rich blocked
        mods_to_remove = [k for k in sys.modules if "_setup_handlers" in k]
        for mod in mods_to_remove:
            del sys.modules[mod]

        # Block rich imports
        with patch.dict(sys.modules, {"rich": None, "rich.console": None, "rich.panel": None}):
            import sagaz.cli._setup_handlers as mod_reloaded

            assert mod_reloaded.console is None
            assert mod_reloaded.Panel is None

        # Restore original module
        for mod in mods_to_remove:
            if mod in sys.modules:
                del sys.modules[mod]
