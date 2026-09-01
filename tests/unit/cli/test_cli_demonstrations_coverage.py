"""
Supplemental coverage tests for sagaz/cli/demonstrations.py.

Targets missing lines:
  - 19-21  (rich ImportError fallback)
  - 27-29  (simple_term_menu ImportError fallback)
  - 168-169 (no demos found branch in list_demos)
  - 204-207 (console=None branch in run_demo)
  - 222->226 (console=None in _show_domain_menu)
  - 274->276 (console=None in _handle_domain_and_demo_selection exit)
  - 282->286 (console=None in _handle_domain_and_demo_selection domain label)
  - 291-298  (click.confirm=False + console goodbye)
  - 330->exit (while loop exit in _domain_menu_loop)
  - 332-335  (_execute_demo KeyboardInterrupt and Exception)
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


# ============================================================================
# Import fallback paths (lines 19-21 and 27-29)
# ============================================================================


class TestImportFallbacks:
    """Tests that cover the ImportError fallback paths at module import time."""

    def test_rich_import_error_fallback(self):
        """Lines 19-21: console=None, TableClass=None when rich is unavailable."""
        import sagaz.cli.demonstrations as mod

        try:
            with patch.dict(sys.modules, {"rich": None, "rich.console": None, "rich.table": None}):
                importlib.reload(mod)
                assert mod.console is None
                assert mod.TableClass is None
        finally:
            importlib.reload(mod)  # restore

    def test_simple_term_menu_import_error_fallback(self):
        """Lines 27-29: TERM_MENU_AVAILABLE=False, TerminalMenu=None when package unavailable."""
        import sagaz.cli.demonstrations as mod

        try:
            with patch.dict(sys.modules, {"simple_term_menu": None}):
                importlib.reload(mod)
                assert mod.TERM_MENU_AVAILABLE is False
                assert mod.TerminalMenu is None
        finally:
            importlib.reload(mod)  # restore


# ============================================================================
# list_demos — empty demos branch (lines 168-169)
# ============================================================================


class TestListDemosEmpty:
    def test_list_demos_no_demos_found(self, capsys):
        """Lines 168-169: list_demos echoes 'No demonstrations found.' when none exist."""
        from sagaz.cli.demonstrations import list_demos

        with patch("sagaz.cli.demonstrations.discover_demos_by_domain", return_value={}):
            list_demos()

        captured = capsys.readouterr()
        assert "No demonstrations found." in captured.out


# ============================================================================
# run_demo — console=None branch (lines 204-207)
# ============================================================================


class TestRunDemoNoConsole:
    def test_run_demo_with_console_none(self, capsys):
        """Lines 204-207: run_demo uses click.echo when console is None."""
        from sagaz.cli.demonstrations import run_demo

        demo_path = Path("/path/to/demo/main.py")
        with (
            patch("sagaz.cli.demonstrations.console", None),
            patch("sagaz.cli.demonstrations.discover_demos", return_value={"my_demo": demo_path}),
            patch("sagaz.cli.demonstrations.get_domain_for_demo", return_value="core_patterns"),
            patch("sagaz.cli.demonstrations._domain_meta_index", return_value={}),
            patch("sagaz.cli.demonstrations._execute_demo"),
        ):
            run_demo("my_demo")

        captured = capsys.readouterr()
        assert "my_demo" in captured.out


# ============================================================================
# _show_domain_menu — console=None branch (line 222->226)
# ============================================================================


class TestShowDomainMenuNoConsole:
    def test_show_domain_menu_no_console(self):
        """Line 222->226: _show_domain_menu skips console.print when console is None."""
        from sagaz.cli.demonstrations import _show_domain_menu

        mock_menu = MagicMock()
        mock_menu.show.return_value = 0

        with (
            patch("sagaz.cli.demonstrations.console", None),
            patch("sagaz.cli.demonstrations.TerminalMenu", return_value=mock_menu),
        ):
            result = _show_domain_menu(
                ["core_patterns"],
                {"core_patterns": {"basic_saga": Path("/demo")}},
                {"core_patterns": {"label": "Core Patterns"}},
            )

        assert result == 0


# ============================================================================
# _handle_domain_and_demo_selection — missing branches (274->276, 282->286, 291-298)
# ============================================================================


class TestHandleDomainAndDemoSelection:
    def test_exit_when_domain_selection_is_none_no_console(self):
        """Lines 274->276: when domain selection returns None and console=None, return False."""
        from sagaz.cli.demonstrations import _handle_domain_and_demo_selection

        with (
            patch("sagaz.cli.demonstrations.console", None),
            patch("sagaz.cli.demonstrations._show_domain_menu", return_value=None),
        ):
            result = _handle_domain_and_demo_selection(
                ["core_patterns"],
                {"core_patterns": {"basic_saga": Path("/demo")}},
                {},
            )

        assert result is False

    def test_domain_selected_no_console(self):
        """Lines 282->286: when domain is selected and console=None, skip label print."""
        from sagaz.cli.demonstrations import _handle_domain_and_demo_selection

        mock_demo_path = Path("/path/to/demo")
        with (
            patch("sagaz.cli.demonstrations.console", None),
            patch("sagaz.cli.demonstrations._show_domain_menu", return_value=0),
            patch("sagaz.cli.demonstrations._show_demo_menu", return_value=None),
        ):
            result = _handle_domain_and_demo_selection(
                ["core_patterns"],
                {"core_patterns": {"basic_saga": mock_demo_path}},
                {"core_patterns": {"label": "Core Patterns"}},
            )

        # Returns True (back to domain selection) because demo_idx is None
        assert result is True

    def test_confirm_no_exits_loop_no_console(self):
        """Lines 291-298: when confirm=False and console=None, return False."""
        from sagaz.cli.demonstrations import _handle_domain_and_demo_selection

        mock_demo_path = Path("/path/to/demo")
        with (
            patch("sagaz.cli.demonstrations.console", None),
            patch("sagaz.cli.demonstrations._show_domain_menu", return_value=0),
            patch("sagaz.cli.demonstrations._show_demo_menu", return_value=0),
            patch("sagaz.cli.demonstrations.run_demo"),
            patch("click.confirm", return_value=False),
        ):
            result = _handle_domain_and_demo_selection(
                ["core_patterns"],
                {"core_patterns": {"basic_saga": mock_demo_path}},
                {"core_patterns": {"label": "Core Patterns"}},
            )

        assert result is False

    def test_confirm_no_exits_loop_with_console(self):
        """Lines 291-298: when confirm=False and console available, print goodbye and return False."""
        from sagaz.cli.demonstrations import _handle_domain_and_demo_selection

        mock_console = MagicMock()
        mock_demo_path = Path("/path/to/demo")
        with (
            patch("sagaz.cli.demonstrations.console", mock_console),
            patch("sagaz.cli.demonstrations._show_domain_menu", return_value=0),
            patch("sagaz.cli.demonstrations._show_demo_menu", return_value=0),
            patch("sagaz.cli.demonstrations.run_demo"),
            patch("click.confirm", return_value=False),
        ):
            result = _handle_domain_and_demo_selection(
                ["core_patterns"],
                {"core_patterns": {"basic_saga": mock_demo_path}},
                {"core_patterns": {"label": "Core Patterns"}},
            )

        assert result is False
        mock_console.print.assert_called()

    def test_confirm_yes_continues_loop(self):
        """Line 298: return True when click.confirm returns True (user wants another demo)."""
        from sagaz.cli.demonstrations import _handle_domain_and_demo_selection

        mock_demo_path = Path("/path/to/demo")
        with (
            patch("sagaz.cli.demonstrations.console", None),
            patch("sagaz.cli.demonstrations._show_domain_menu", return_value=0),
            patch("sagaz.cli.demonstrations._show_demo_menu", return_value=0),
            patch("sagaz.cli.demonstrations.run_demo"),
            patch("click.confirm", return_value=True),
        ):
            result = _handle_domain_and_demo_selection(
                ["core_patterns"],
                {"core_patterns": {"basic_saga": mock_demo_path}},
                {},
            )

        assert result is True


class TestDomainMenuLoop:
    def test_domain_menu_loop_exits_on_false(self):
        """Line 330->exit: _domain_menu_loop exits when handler returns False."""
        from sagaz.cli.demonstrations import _domain_menu_loop

        with (
            patch(
                "sagaz.cli.demonstrations.discover_demos_by_domain",
                return_value={"core_patterns": {"basic_saga": Path("/demo")}},
            ),
            patch(
                "sagaz.cli.demonstrations._handle_domain_and_demo_selection",
                return_value=False,
            ),
        ):
            _domain_menu_loop()  # Should return normally without infinite loop


# ============================================================================
# _execute_demo — exception branches (lines 332-335)
# ============================================================================


class TestExecuteDemo:
    def test_execute_demo_keyboard_interrupt(self, capsys):
        """Line 332-333: _execute_demo catches KeyboardInterrupt."""
        from sagaz.cli.demonstrations import _execute_demo

        with patch("subprocess.run", side_effect=KeyboardInterrupt()):
            _execute_demo(Path("/path/to/demo/main.py"))

        captured = capsys.readouterr()
        assert "interrupted" in captured.out.lower()

    def test_execute_demo_generic_exception(self, capsys):
        """Lines 334-335: _execute_demo catches generic Exception."""
        from sagaz.cli.demonstrations import _execute_demo

        with patch("subprocess.run", side_effect=OSError("Permission denied")):
            _execute_demo(Path("/path/to/demo/main.py"))

        captured = capsys.readouterr()
        assert "Error running demonstration" in captured.out or "Permission denied" in captured.out

    def test_execute_demo_nonzero_exit(self, capsys):
        """Line 330: _execute_demo reports non-zero exit code."""
        from sagaz.cli.demonstrations import _execute_demo

        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            _execute_demo(Path("/path/to/demo/main.py"))

        captured = capsys.readouterr()
        assert "exited with code 1" in captured.out or "1" in captured.out

    def test_execute_demo_zero_exit(self):
        """Line 330->exit: _execute_demo exits normally when returncode==0."""
        from sagaz.cli.demonstrations import _execute_demo

        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            _execute_demo(Path("/path/to/demo/main.py"))
        # No output expected for successful completion
