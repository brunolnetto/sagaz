"""
Tests for CLI examples module.
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.cli.examples import (
    _execute_example,
    _fallback_interactive_simple,
    discover_examples,
    get_categories,
    get_example_description,
    get_examples_dir,
    interactive_cmd,
    list_examples_cmd,
    run_example_cmd,
)


class TestGetExamplesDir:
    """Tests for get_examples_dir function."""

    def test_returns_path(self):
        """Test that get_examples_dir returns a Path object."""
        result = get_examples_dir()
        assert isinstance(result, Path)

    def test_path_ends_with_examples(self):
        """Test that the path ends with 'examples'."""
        result = get_examples_dir()
        assert result.name == "examples"


class TestGetCategories:
    """Tests for get_categories function."""

    def test_returns_list(self):
        """Test that get_categories returns a list."""
        result = get_categories()
        assert isinstance(result, list)

    def test_returns_sorted_categories(self):
        """Test that categories are sorted alphabetically."""
        result = get_categories()
        assert result == sorted(result)

    @patch("sagaz.cli.examples.get_examples_dir")
    def test_empty_when_dir_not_exists(self, mock_dir):
        """Test returns empty list when examples dir doesn't exist."""
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_dir.return_value = mock_path

        result = get_categories()
        assert result == []


class TestDiscoverExamples:
    """Tests for discover_examples function."""

    def test_returns_dict(self):
        """Test that discover_examples returns a dict."""
        result = discover_examples()
        assert isinstance(result, dict)

    def test_category_filter(self):
        """Test filtering by category."""
        # Get all examples first
        all_examples = discover_examples()

        if all_examples:
            # Get the first category from any example
            first_name = next(iter(all_examples.keys()))
            if "/" in first_name:
                category = first_name.split("/")[0]
                filtered = discover_examples(category=category)

                # All filtered examples should be in that category
                for name in filtered:
                    assert name.startswith(category)

    @patch("sagaz.cli.examples.get_examples_dir")
    def test_empty_when_dir_not_exists(self, mock_dir):
        """Test returns empty dict when examples dir doesn't exist."""
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_dir.return_value = mock_path

        result = discover_examples()
        assert result == {}

    @patch("sagaz.cli.examples.get_examples_dir")
    def test_category_not_found(self, mock_dir):
        """Test returns empty dict when category dir doesn't exist."""
        mock_examples = MagicMock()
        mock_examples.exists.return_value = True

        mock_category = MagicMock()
        mock_category.exists.return_value = False
        mock_examples.__truediv__ = MagicMock(return_value=mock_category)

        mock_dir.return_value = mock_examples

        result = discover_examples(category="nonexistent")
        assert result == {}


class TestGetExampleDescription:
    """Tests for get_example_description function."""

    def test_returns_string(self, tmp_path):
        """Test that get_example_description returns a string."""
        # Create a temp file with a docstring
        test_file = tmp_path / "main.py"
        test_file.write_text('"""Test description."""\nprint("hello")')

        result = get_example_description(test_file)
        assert isinstance(result, str)

    def test_extracts_docstring(self, tmp_path):
        """Test that docstring is extracted."""
        test_file = tmp_path / "main.py"
        test_file.write_text('"""This is a test example."""\nprint("hello")')

        result = get_example_description(test_file)
        assert "test example" in result.lower()

    def test_no_docstring(self, tmp_path):
        """Test returns 'No description' when no docstring."""
        test_file = tmp_path / "main.py"
        test_file.write_text('print("hello")')

        result = get_example_description(test_file)
        assert result == "No description"

    def test_empty_docstring(self, tmp_path):
        """Test handles empty docstring."""
        test_file = tmp_path / "main.py"
        test_file.write_text('"""\nActual description on next line\n"""\nprint("hello")')

        result = get_example_description(test_file)
        assert result != ""

    def test_file_not_found(self):
        """Test handles missing file gracefully."""
        result = get_example_description(Path("/nonexistent/path/main.py"))
        assert result == "No description"


class TestListExamplesCmd:
    """Tests for list_examples_cmd function."""

    @patch("sagaz.cli.examples.discover_examples")
    @patch("sagaz.cli.examples.console")
    def test_no_examples_found(self, mock_console, mock_discover):
        """Test output when no examples found."""
        mock_discover.return_value = {}
        mock_console.print = MagicMock()

        # Should not raise
        list_examples_cmd()

    @patch("sagaz.cli.examples.discover_examples")
    @patch("sagaz.cli.examples.console")
    @patch("sagaz.cli.examples.Table")
    def test_examples_listed(self, mock_table_class, mock_console, mock_discover):
        """Test examples are listed in table."""
        mock_discover.return_value = {
            "test/example": Path("/tmp/test/example/main.py")
        }
        mock_table = MagicMock()
        mock_table_class.return_value = mock_table
        mock_console.print = MagicMock()

        list_examples_cmd()

        mock_table.add_row.assert_called()

    @patch("sagaz.cli.examples.discover_examples")
    @patch("sagaz.cli.examples.get_categories")
    def test_category_filter_message(self, mock_categories, mock_discover):
        """Test shows available categories when filter fails."""
        mock_discover.return_value = {}
        mock_categories.return_value = ["ecommerce", "fintech"]

        # Should not raise
        list_examples_cmd(category="nonexistent")


class TestRunExampleCmd:
    """Tests for run_example_cmd function."""

    @patch("sagaz.cli.examples.discover_examples")
    @patch("click.echo")
    def test_example_not_found(self, mock_echo, mock_discover):
        """Test output when example not found."""
        mock_discover.return_value = {}

        run_example_cmd("nonexistent")

        # Should show error message
        mock_echo.assert_called()
        call_args = str(mock_echo.call_args_list)
        assert "not found" in call_args.lower()

    @patch("sagaz.cli.examples.discover_examples")
    @patch("sagaz.cli.examples._execute_example")
    @patch("click.echo")
    def test_example_executed(self, mock_echo, mock_execute, mock_discover):
        """Test example is executed when found."""
        mock_discover.return_value = {
            "test/example": Path("/tmp/test/example/main.py")
        }

        run_example_cmd("test/example")

        mock_execute.assert_called_once()


class TestExecuteExample:
    """Tests for _execute_example function."""

    @patch("subprocess.run")
    @patch("sys.executable", "/usr/bin/python3")
    def test_runs_subprocess(self, mock_run):
        """Test that subprocess is called."""
        script_path = Path("/tmp/test/main.py")

        _execute_example(script_path)

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "/usr/bin/python3" in args[0]
        assert str(script_path) in args[1]

    @patch("subprocess.run")
    @patch("click.echo")
    def test_handles_subprocess_error(self, mock_echo, mock_run):
        """Test handles subprocess failure."""
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "python")

        _execute_example(Path("/tmp/test/main.py"))

        # Should show error message
        call_args = str(mock_echo.call_args)
        assert "exit code" in call_args.lower()

    @patch("subprocess.run")
    @patch("click.echo")
    def test_handles_keyboard_interrupt(self, mock_echo, mock_run):
        """Test handles Ctrl+C gracefully."""
        mock_run.side_effect = KeyboardInterrupt()

        _execute_example(Path("/tmp/test/main.py"))

        mock_echo.assert_called()


class TestInteractiveCmd:
    """Tests for interactive_cmd function."""

    @patch("sagaz.cli.examples.TERM_MENU_AVAILABLE", False)
    @patch("sagaz.cli.examples.discover_examples")
    @patch("click.echo")
    def test_no_examples_found(self, mock_echo, mock_discover):
        """Test output when no examples found."""
        mock_discover.return_value = {}

        interactive_cmd()

        mock_echo.assert_called()

    @patch("sagaz.cli.examples.TERM_MENU_AVAILABLE", False)
    @patch("sagaz.cli.examples.discover_examples")
    @patch("sagaz.cli.examples._fallback_interactive_simple")
    def test_uses_fallback_when_no_term_menu(self, mock_fallback, mock_discover):
        """Test falls back to numbered menu when term menu unavailable."""
        mock_discover.return_value = {"test": Path("/tmp/test/main.py")}

        interactive_cmd()

        # Should call fallback when term menu not available
        mock_fallback.assert_called_once()

    @patch("sagaz.cli.examples.TERM_MENU_AVAILABLE", True)
    @patch("sagaz.cli.examples._category_menu_loop")
    def test_uses_term_menu_when_available(self, mock_menu_loop):
        """Test uses term menu when available and no category specified."""
        interactive_cmd()

        mock_menu_loop.assert_called_once()

    @patch("sagaz.cli.examples.TERM_MENU_AVAILABLE", True)
    @patch("sagaz.cli.examples._examples_menu_loop")
    def test_uses_examples_menu_with_category(self, mock_menu_loop):
        """Test goes directly to examples menu when category specified."""
        interactive_cmd(category="ecommerce")

        mock_menu_loop.assert_called_once_with("ecommerce")


class TestFallbackInteractive:
    """Tests for _fallback_interactive_simple function."""

    @patch("sagaz.cli.examples.discover_examples")
    @patch("click.prompt")
    @patch("click.echo")
    @patch("sagaz.cli.examples.get_example_description")
    def test_quit_option(self, mock_desc, mock_echo, mock_prompt, mock_discover):
        """Test user can quit with 0."""
        mock_discover.return_value = {"test/example": Path("/tmp/test/main.py")}
        mock_prompt.return_value = 0
        mock_desc.return_value = "Description"

        _fallback_interactive_simple()

        # Should not raise

    @patch("sagaz.cli.examples.discover_examples")
    @patch("builtins.input")
    @patch("click.prompt")
    @patch("click.echo")
    @patch("sagaz.cli.examples.get_example_description")
    @patch("sagaz.cli.examples._execute_example")
    def test_selects_example(self, mock_execute, mock_desc, mock_echo, mock_prompt, mock_input, mock_discover):
        """Test user can select an example."""
        mock_discover.return_value = {"test/example": Path("/tmp/test/main.py")}
        # First return 1 (select), then 0 to exit loop
        mock_prompt.side_effect = [1, 0]
        mock_desc.return_value = "Description"
        mock_input.return_value = ""  # Press enter to continue

        _fallback_interactive_simple()

    @patch("sagaz.cli.examples.discover_examples")
    @patch("click.prompt")
    @patch("click.echo")
    @patch("sagaz.cli.examples.get_example_description")
    def test_invalid_number(self, mock_desc, mock_echo, mock_prompt, mock_discover):
        """Test handles invalid number."""
        mock_discover.return_value = {"test/example": Path("/tmp/test/main.py")}
        mock_prompt.side_effect = [99, 0]  # Invalid then quit
        mock_desc.return_value = "Description"

        _fallback_interactive_simple()

    @patch("sagaz.cli.examples.discover_examples")
    @patch("click.prompt")
    @patch("click.echo")
    @patch("sagaz.cli.examples.get_example_description")
    def test_value_error(self, mock_desc, mock_echo, mock_prompt, mock_discover):
        """Test handles ValueError from non-numeric input."""
        mock_discover.return_value = {"test/example": Path("/tmp/test/main.py")}
        mock_prompt.side_effect = ValueError("not a number")
        mock_desc.return_value = "Description"

        _fallback_interactive_simple()

    @patch("sagaz.cli.examples.discover_examples")
    @patch("click.echo")
    def test_no_examples(self, mock_echo, mock_discover):
        """Test handles no examples found."""
        mock_discover.return_value = {}

        _fallback_interactive_simple()

        mock_echo.assert_called()

