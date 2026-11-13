"""Tests for sagaz.cli.replay_ui display helpers (Rich and plain-text paths)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sagaz.cli import replay_ui


@pytest.fixture
def echo():
    return MagicMock()


@pytest.fixture
def con():
    return MagicMock()


def _printed(con) -> list:
    return [c.args[0] for c in con.print.call_args_list]


def _echoed(echo) -> list[str]:
    return [c.args[0] for c in echo.call_args_list]


def _result(status="success", error=None):
    return SimpleNamespace(
        replay_status=SimpleNamespace(value=status),
        original_saga_id="orig",
        new_saga_id="new",
        checkpoint_step="step-2",
        error_message=error,
    )


def _state(context=None):
    return SimpleNamespace(
        timestamp="2026-01-01T00:00:00Z",
        saga_id="saga-1",
        saga_name="OrderSaga",
        status="completed",
        current_step=None,
        step_index=2,
        completed_steps=["a", "b"],
        context={"order": 1} if context is None else context,
        to_dict=lambda: {"saga_id": "saga-1"},
    )


def _change(step="pay"):
    return SimpleNamespace(
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        current_step=step,
        status="running",
        completed_steps=["reserve"],
    )


CHECKPOINTS = [{"step_name": "reserve", "created_at": "t1"}]


class TestModuleDefaults:
    def test_rich_is_detected_and_reexported(self):
        assert replay_ui.HAS_RICH is True
        assert replay_ui.console is not None

    def test_default_flags_use_module_console(self, monkeypatch, con):
        """rich_available=None and console=None fall back to module-level Rich state."""
        monkeypatch.setattr(replay_ui, "_console", con)
        replay_ui.display_success()
        replay_ui.display_failure()
        replay_ui.handle_exception(ValueError("boom"), verbose=False)
        replay_ui.display_replay_config("s", "step", "memory", {}, dry_run=False)
        replay_ui.show_checkpoints(CHECKPOINTS, verbose=True)
        replay_ui.show_replay_result(_result(), verbose=True, dry_run=False)
        replay_ui.display_full_state(_state(), "table")
        replay_ui.display_changes([_change()], "saga-1")
        assert con.print.call_count >= 8

    def test_default_echo_is_click(self, monkeypatch):
        echo = MagicMock()
        monkeypatch.setattr(replay_ui.click, "echo", echo)
        replay_ui.display_key_value("k", 1, "text")
        replay_ui._display_state_text(_state())
        assert _echoed(echo)[0] == "k: 1"


class TestSimpleMessages:
    def test_success_rich_and_text(self, echo, con):
        replay_ui.display_success(rich_available=True, echo_func=echo, console=con)
        replay_ui.display_success(rich_available=False, echo_func=echo, console=con)
        assert "completed successfully" in _printed(con)[0]
        echo.assert_called_once_with("✓ Replay completed successfully")

    def test_failure_text_goes_to_stderr(self, echo, con):
        replay_ui.display_failure(rich_available=True, echo_func=echo, console=con)
        replay_ui.display_failure(rich_available=False, echo_func=echo, console=con)
        assert "Replay failed" in _printed(con)[0]
        echo.assert_called_once_with("✗ Replay failed", err=True)

    def test_exception_text_and_verbose_traceback(self, echo, con, capsys):
        message = "kaput"
        try:
            raise RuntimeError(message)
        except RuntimeError as exc:
            replay_ui.handle_exception(exc, True, rich_available=False, echo_func=echo)
            replay_ui.handle_exception(exc, False, rich_available=True, console=con)
        echo.assert_called_once_with("Error: kaput", err=True)
        assert "Error: kaput" in _printed(con)[0]
        assert "RuntimeError: kaput" in capsys.readouterr().err

    def test_rich_requested_without_console_uses_echo(self, monkeypatch, echo):
        monkeypatch.setattr(replay_ui, "_console", None)
        replay_ui.display_success(rich_available=True, echo_func=echo)
        echo.assert_called_once()


class TestReplayConfig:
    def test_rich_panel(self, con):
        replay_ui.display_replay_config(
            "s1", "pay", "redis", {"a": 1}, True, rich_available=True, console=con
        )
        panel = _printed(con)[0]
        assert panel.title == "Replay Configuration"
        assert "Overrides: 1" in panel.renderable
        assert "Dry Run: True" in panel.renderable

    def test_text(self, echo):
        replay_ui.display_replay_config(
            "s1", "pay", "redis", {}, False, rich_available=False, echo_func=echo
        )
        echo.assert_called_once_with("Replaying saga s1 from step pay...")

    def test_rich_without_panel_is_noop(self, monkeypatch, con):
        monkeypatch.setattr(replay_ui, "Panel", None)
        replay_ui.display_replay_config("s", "p", "m", {}, False, rich_available=True, console=con)
        con.print.assert_not_called()


class TestCheckpoints:
    def test_not_verbose_is_silent(self, echo, con):
        replay_ui.show_checkpoints(CHECKPOINTS, False, echo_func=echo, console=con)
        echo.assert_not_called()
        con.print.assert_not_called()

    def test_rich_table(self, con):
        replay_ui.show_checkpoints(CHECKPOINTS, True, rich_available=True, console=con)
        table = _printed(con)[0]
        assert table.title == "Available Checkpoints"
        assert table.row_count == 1

    def test_text(self, echo):
        replay_ui.show_checkpoints(CHECKPOINTS, True, rich_available=False, echo_func=echo)
        assert _echoed(echo) == ["\nAvailable checkpoints:", "  - reserve at t1"]

    def test_rich_without_table_is_noop(self, monkeypatch, con):
        monkeypatch.setattr(replay_ui, "Table", None)
        replay_ui.show_checkpoints(CHECKPOINTS, True, rich_available=True, console=con)
        con.print.assert_not_called()


class TestReplayResult:
    def test_quiet_unless_verbose_or_dry_run(self, echo, con):
        replay_ui.show_replay_result(_result(), False, False, echo_func=echo, console=con)
        echo.assert_not_called()
        con.print.assert_not_called()

    @pytest.mark.parametrize(("status", "border"), [("success", "green"), ("failed", "red")])
    def test_rich_border_reflects_status(self, con, status, border):
        replay_ui.show_replay_result(_result(status), False, True, rich_available=True, console=con)
        panel = _printed(con)[0]
        assert panel.border_style == border
        assert "Error: None" in panel.renderable

    def test_text_includes_error_only_when_present(self, echo):
        replay_ui.show_replay_result(_result(), True, False, rich_available=False, echo_func=echo)
        assert not any(line.startswith("Error") for line in _echoed(echo))
        echo.reset_mock()
        replay_ui.show_replay_result(
            _result("failed", "bad step"), True, False, rich_available=False, echo_func=echo
        )
        assert _echoed(echo)[-1] == "Error: bad step"

    def test_rich_without_panel_is_noop(self, monkeypatch, con):
        monkeypatch.setattr(replay_ui, "Panel", None)
        replay_ui.show_replay_result(_result(), True, False, rich_available=True, console=con)
        con.print.assert_not_called()


class TestState:
    def test_key_value_json_and_text(self, echo):
        replay_ui.display_key_value("amount", 10, "json", echo_func=echo)
        replay_ui.display_key_value("amount", 10, "text", echo_func=echo)
        assert _echoed(echo) == ['{\n  "amount": 10\n}', "amount: 10"]

    def test_full_state_json(self, echo, con):
        replay_ui.display_full_state(
            _state(), "json", rich_available=True, echo_func=echo, console=con
        )
        echo.assert_called_once_with('{\n  "saga_id": "saga-1"\n}')
        con.print.assert_not_called()

    def test_full_state_table_prints_table_and_context(self, con):
        replay_ui.display_full_state(_state(), "table", rich_available=True, console=con)
        printed = _printed(con)
        assert printed[0].row_count == 6
        assert printed[1] == "\n[bold]Context:[/bold]"
        assert len(printed) == 3

    @pytest.mark.parametrize("output_format", ["table", "text"])
    def test_full_state_falls_back_to_text(self, echo, output_format):
        replay_ui.display_full_state(_state(), output_format, rich_available=False, echo_func=echo)
        lines = _echoed(echo)
        assert "Completed Steps: a, b" in lines
        assert lines[-1] == "  order: 1"

    def test_text_with_no_completed_steps(self, echo):
        state = _state()
        state.completed_steps = []
        replay_ui._display_state_text(state, echo_func=echo)
        assert "Completed Steps: None" in _echoed(echo)

    def test_table_skips_context_when_json_unavailable(self, monkeypatch, con):
        monkeypatch.setattr(replay_ui, "JSON", None)
        replay_ui._display_state_table(_state(), console=con)
        assert con.print.call_count == 1

    def test_table_without_table_class_is_noop(self, monkeypatch, con):
        monkeypatch.setattr(replay_ui, "Table", None)
        replay_ui._display_state_table(_state(), console=con)
        con.print.assert_not_called()

    def test_table_without_any_console_is_noop(self, monkeypatch):
        monkeypatch.setattr(replay_ui, "_console", None)
        replay_ui._display_state_table(_state())  # must not raise


class TestChanges:
    def test_rich_table_and_total(self, con):
        replay_ui.display_changes(
            [_change(), _change(None)], "saga-1", rich_available=True, console=con
        )
        table, total = _printed(con)
        assert table.title == "State Changes for saga-1"
        assert table.row_count == 2
        assert "Total: 2 changes" in total

    def test_text(self, echo):
        replay_ui.display_changes([_change()], "saga-1", rich_available=False, echo_func=echo)
        lines = _echoed(echo)
        assert lines[0] == "State changes for saga-1:"
        assert "Step: pay, Status: running, Completed: 1" in lines[1]
        assert lines[-1] == "\nTotal: 1 changes"

    def test_rich_without_table_is_noop(self, monkeypatch, con):
        monkeypatch.setattr(replay_ui, "Table", None)
        replay_ui.display_changes([_change()], "s", rich_available=True, console=con)
        con.print.assert_not_called()
