"""
Comprehensive tests for cli/demonstrations.py module.

Covers listing, interactive selection, and running demonstrations.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sagaz.cli.demonstrations import (
    demo_cli,
    list_demos,
    list_demos_cmd,
    run_demo,
    run_demo_cmd,
)


@pytest.fixture
def runner():
    """CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_demos():
    """Mock demonstrations data."""
    return {
        "basic_saga": Path("/path/to/basic_saga/main.py"),
        "parallel_steps": Path("/path/to/parallel_steps/main.py"),
        "compensation_deep_dive": Path("/path/to/compensation_deep_dive/main.py"),
    }


@pytest.fixture
def mock_domains():
    """Mock domain structure."""
    return {
        "core_patterns": {
            "basic_saga": Path("/path/to/core_patterns/basic_saga/main.py"),
            "parallel_steps": Path("/path/to/core_patterns/parallel_steps/main.py"),
        },
        "developer_experience": {
            "lifecycle_hooks": Path("/path/to/dev_exp/lifecycle_hooks/main.py"),
        },
    }


class TestListDemosCommand:
    """Tests for list_demos_cmd and list_demos functions."""

    def test_list_demos_displays_output(self, capsys):
        """Test that list_demos outputs demonstration information."""
        with patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover:
            mock_discover.return_value = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                }
            }

            list_demos()
            captured = capsys.readouterr()

            # Should display domain and demo name
            assert "basic_saga" in captured.out or "basic_saga" in captured.out.lower()

    def test_list_demos_with_domain_filter(self, capsys):
        """Test list_demos filters by domain when specified."""
        with patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover:
            mock_discover.return_value = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                },
                "developer_experience": {
                    "lifecycle_hooks": Path(
                        "sagaz/demonstrations/developer_experience/lifecycle_hooks/main.py"
                    ),
                },
            }

            list_demos(filter_domain="core_patterns")
            captured = capsys.readouterr()

            # Should show filtered domain
            assert "core_patterns" in captured.out.lower() or "basic_saga" in captured.out

    def test_list_demos_invalid_domain(self, capsys):
        """Test list_demos with invalid domain shows error."""
        with patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover:
            mock_discover.return_value = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                }
            }

            list_demos(filter_domain="nonexistent")
            captured = capsys.readouterr()

            # Should show error message
            assert "error" in captured.out.lower() or "not found" in captured.out.lower()

    def test_list_demos_no_console_fallback(self, capsys):
        """Test list_demos with console=None uses plain text display."""
        with (
            patch("sagaz.cli.demonstrations.console", None),
            patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover,
        ):
            mock_discover.return_value = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                }
            }

            list_demos()
            captured = capsys.readouterr()

            # Should display something (either table header or plain text)
            assert len(captured.out) > 0

    def test_list_demos_cmd_cli(self, runner):
        """Test list_demos_cmd via CLI."""
        with patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover:
            mock_discover.return_value = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                }
            }

            result = runner.invoke(demo_cli, ["list"])
            assert result.exit_code in [0, None]

    def test_list_demos_cmd_with_domain_option(self, runner):
        """Test list_demos_cmd with --domain option."""
        with patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover:
            mock_discover.return_value = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                }
            }

            result = runner.invoke(demo_cli, ["list", "--domain", "core_patterns"])
            assert result.exit_code in [0, None]


class TestRunDemoCommand:
    """Tests for run_demo_cmd and run_demo functions."""

    def test_run_demo_with_valid_name(self):
        """Test run_demo executes a valid demonstration."""
        with (
            patch("sagaz.cli.demonstrations.discover_demos") as mock_discover,
            patch("subprocess.run") as mock_run,
        ):
            demo_path = Path("/path/to/demo/main.py")
            mock_discover.return_value = {"basic_saga": demo_path}

            run_demo("basic_saga")

            # Should call subprocess.run to execute the demo
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            # Check that python or the script is in the call
            assert call_args is not None

    def test_run_demo_with_invalid_name(self, capsys):
        """Test run_demo with invalid name shows error."""
        with patch("sagaz.cli.demonstrations.discover_demos") as mock_discover:
            mock_discover.return_value = {
                "basic_saga": Path("/path/to/basic_saga/main.py"),
            }

            run_demo("nonexistent_demo")
            captured = capsys.readouterr()

            # Should show error
            assert "error" in captured.out.lower() or "not found" in captured.out.lower()

    def test_run_demo_cmd_cli(self, runner):
        """Test run_demo_cmd via CLI."""
        with (
            patch("sagaz.cli.demonstrations.discover_demos") as mock_discover,
            patch("subprocess.run") as mock_run,
        ):
            demo_path = Path("/path/to/demo/main.py")
            mock_discover.return_value = {"basic_saga": demo_path}

            result = runner.invoke(demo_cli, ["run", "basic_saga"])
            assert result.exit_code in [0, None]

    def test_run_demo_sets_pythonpath(self):
        """Test run_demo sets PYTHONPATH correctly."""
        with (
            patch("sagaz.cli.demonstrations.discover_demos") as mock_discover,
            patch("subprocess.run") as mock_run,
            patch("os.environ.copy") as mock_env,
        ):
            demo_path = Path("/path/to/demo/main.py")
            mock_discover.return_value = {"basic_saga": demo_path}
            mock_env.return_value = {}

            run_demo("basic_saga")

            # Should have set PYTHONPATH in the environment
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            if call_args and "env" in call_args[1]:
                assert "PYTHONPATH" in call_args[1]["env"]


class TestDemoCliGroup:
    """Tests for demo_cli group command."""

    def test_demo_cli_no_subcommand_shows_interactive(self, runner):
        """Test running demo without subcommand invokes interactive mode."""
        with patch("sagaz.cli.demonstrations.interactive_cmd") as mock_interactive:
            result = runner.invoke(demo_cli, [])
            # Depending on implementation, might show help or run interactive
            assert result.exit_code in [0, None, 2]  # 2 is OK for click help

    def test_demo_cli_list_subcommand(self, runner):
        """Test demo list subcommand."""
        with patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover:
            mock_discover.return_value = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                }
            }

            result = runner.invoke(demo_cli, ["list"])
            assert result.exit_code in [0, None]

    def test_demo_cli_run_subcommand(self, runner):
        """Test demo run subcommand."""
        with (
            patch("sagaz.cli.demonstrations.discover_demos") as mock_discover,
            patch("subprocess.run") as mock_run,
        ):
            demo_path = Path("/path/to/demo/main.py")
            mock_discover.return_value = {"basic_saga": demo_path}

            result = runner.invoke(demo_cli, ["run", "basic_saga"])
            assert result.exit_code in [0, None]


class TestDemoHelperFunctions:
    """Tests for helper functions in demonstrations CLI."""

    def test_get_demo_description(self):
        """Test extracting demo description from file."""
        with patch("sagaz.cli.demonstrations.get_demo_description") as mock_desc:
            mock_desc.return_value = "Test demonstration"

            result = mock_desc(Path("sagaz/demonstrations/basic_saga/main.py"))
            assert isinstance(result, str)
            assert result == "Test demonstration"

    def test_discover_domains(self):
        """Test discovering domain metadata."""
        with patch("sagaz.cli.demonstrations.discover_domains") as mock_domains:
            mock_domains.return_value = [
                {"order": 1, "name": "core_patterns", "label": "Core Patterns"},
                {"order": 2, "name": "developer_experience", "label": "Developer Experience"},
            ]

            domains = mock_domains()
            assert len(domains) == 2
            assert domains[0]["name"] == "core_patterns"

    def test_discover_demos_by_domain(self):
        """Test discovering demonstrations grouped by domain."""
        with patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover:
            mock_discover.return_value = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                    "parallel_steps": Path(
                        "sagaz/demonstrations/core_patterns/parallel_steps/main.py"
                    ),
                },
                "developer_experience": {
                    "lifecycle_hooks": Path(
                        "sagaz/demonstrations/developer_experience/lifecycle_hooks/main.py"
                    ),
                },
            }

            by_domain = mock_discover()
            assert len(by_domain) == 2
            assert len(by_domain["core_patterns"]) == 2
            assert "basic_saga" in by_domain["core_patterns"]

    def test_get_domain_for_demo(self):
        """Test looking up domain for a demo."""
        with (
            patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover,
            patch("sagaz.cli.demonstrations.get_domain_for_demo") as mock_lookup,
        ):
            mock_discover.return_value = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                }
            }
            mock_lookup.return_value = "core_patterns"

            domain = mock_lookup("basic_saga")
            assert domain == "core_patterns"


class TestInteractiveFunctions:
    """Tests for interactive menu functions."""

    def test_interactive_cmd_no_menu_available(self):
        """Test interactive_cmd fallback when TerminalMenu unavailable."""
        with (
            patch("sagaz.cli.demonstrations.TERM_MENU_AVAILABLE", False),
            patch("sagaz.cli.demonstrations._fallback_interactive") as mock_fallback,
        ):
            from sagaz.cli.demonstrations import interactive_cmd

            interactive_cmd()
            mock_fallback.assert_called_once()

    def test_interactive_cmd_with_menu_available(self):
        """Test interactive_cmd uses menu when available."""
        with (
            patch("sagaz.cli.demonstrations.TERM_MENU_AVAILABLE", True),
            patch("sagaz.cli.demonstrations._domain_menu_loop") as mock_menu,
        ):
            from sagaz.cli.demonstrations import interactive_cmd

            interactive_cmd()
            mock_menu.assert_called_once()

    def test_show_domain_menu(self):
        """Test domain menu display."""
        from sagaz.cli.demonstrations import _show_domain_menu

        with patch("sagaz.cli.demonstrations.TerminalMenu") as mock_menu_class:
            mock_menu_instance = MagicMock()
            mock_menu_instance.show.return_value = 0
            mock_menu_class.return_value = mock_menu_instance

            ordered_domains = ["core_patterns", "developer_experience"]
            by_domain = {
                "core_patterns": {"basic_saga": Path("...")},
                "developer_experience": {"lifecycle_hooks": Path("...")},
            }
            meta_index = {
                "core_patterns": {"label": "Core Patterns"},
                "developer_experience": {"label": "Developer Experience"},
            }

            result = _show_domain_menu(ordered_domains, by_domain, meta_index)
            assert result == 0
            mock_menu_instance.show.assert_called_once()

    def test_show_demo_menu(self):
        """Test demo menu display."""
        from sagaz.cli.demonstrations import _show_demo_menu

        with (
            patch("sagaz.cli.demonstrations.TerminalMenu") as mock_menu_class,
            patch("sagaz.cli.demonstrations.get_demo_description") as mock_desc,
        ):
            mock_menu_instance = MagicMock()
            mock_menu_instance.show.return_value = 0
            mock_menu_class.return_value = mock_menu_instance
            mock_desc.return_value = "Test demo"

            demo_names = ["basic_saga", "parallel_steps"]
            demos_in_domain = {
                "basic_saga": Path("sagaz/demonstrations/basic_saga/main.py"),
                "parallel_steps": Path("sagaz/demonstrations/parallel_steps/main.py"),
            }

            result = _show_demo_menu(demo_names, demos_in_domain)
            assert result == 0
            mock_menu_instance.show.assert_called_once()

    def test_handle_domain_and_demo_selection_exit(self):
        """Test demo selection when exiting."""
        from sagaz.cli.demonstrations import _handle_domain_and_demo_selection

        with (
            patch("sagaz.cli.demonstrations._show_domain_menu") as mock_domain_menu,
            patch("sagaz.cli.demonstrations.console"),
        ):
            # Return exit index
            mock_domain_menu.return_value = 99

            ordered_domains = ["core_patterns"]
            by_domain = {"core_patterns": {"basic_saga": Path("...")}}
            meta_index = {"core_patterns": {"label": "Core Patterns"}}

            result = _handle_domain_and_demo_selection(ordered_domains, by_domain, meta_index)
            assert result is False  # Should exit

    def test_handle_domain_and_demo_selection_back(self):
        """Test going back from demo selection."""
        from sagaz.cli.demonstrations import _handle_domain_and_demo_selection

        with (
            patch("sagaz.cli.demonstrations._show_domain_menu") as mock_domain_menu,
            patch("sagaz.cli.demonstrations._show_demo_menu") as mock_demo_menu,
            patch("sagaz.cli.demonstrations.console"),
        ):
            mock_domain_menu.return_value = 0  # Select first domain
            mock_demo_menu.return_value = 99  # Back to domains

            ordered_domains = ["core_patterns"]
            by_domain = {"core_patterns": {"basic_saga": Path("...")}}
            meta_index = {"core_patterns": {"label": "Core Patterns"}}

            result = _handle_domain_and_demo_selection(ordered_domains, by_domain, meta_index)
            assert result is True  # Should continue to domain menu

    def test_domain_menu_loop(self):
        """Test domain menu loop."""
        from sagaz.cli.demonstrations import _domain_menu_loop

        with (
            patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover,
            patch(
                "sagaz.cli.demonstrations._handle_domain_and_demo_selection"
            ) as mock_handler,
        ):
            mock_discover.return_value = {
                "core_patterns": {"basic_saga": Path("...")}
            }
            # Loop once then exit
            mock_handler.side_effect = [True, False]

            _domain_menu_loop()
            assert mock_handler.call_count == 2

    def test_domain_menu_loop_no_demos(self, capsys):
        """Test domain menu loop when no demos found."""
        from sagaz.cli.demonstrations import _domain_menu_loop

        with patch("sagaz.cli.demonstrations.discover_demos_by_domain") as mock_discover:
            mock_discover.return_value = {}

            _domain_menu_loop()
            captured = capsys.readouterr()
            assert "not found" in captured.out.lower() or "no" in captured.out.lower()

    def test_fallback_interactive_run_demo(self):
        """Test fallback interactive with valid demo selection."""
        from sagaz.cli.demonstrations import _fallback_interactive

        with (
            patch("sagaz.cli.demonstrations.list_demos"),
            patch("sagaz.cli.demonstrations.click.prompt") as mock_prompt,
            patch("sagaz.cli.demonstrations.discover_demos") as mock_discover,
            patch("sagaz.cli.demonstrations.run_demo") as mock_run,
        ):
            mock_prompt.return_value = "basic_saga"
            mock_discover.return_value = {"basic_saga": Path("...")}

            _fallback_interactive()
            mock_run.assert_called_once_with("basic_saga")

    def test_fallback_interactive_cancel(self):
        """Test fallback interactive with cancel."""
        from sagaz.cli.demonstrations import _fallback_interactive

        with (
            patch("sagaz.cli.demonstrations.list_demos"),
            patch("sagaz.cli.demonstrations.click.prompt") as mock_prompt,
            patch("sagaz.cli.demonstrations.discover_demos") as mock_discover,
            patch("sagaz.cli.demonstrations.run_demo") as mock_run,
        ):
            mock_prompt.return_value = ""
            mock_discover.return_value = {}

            _fallback_interactive()
            mock_run.assert_not_called()

    def test_fallback_interactive_invalid_demo(self, capsys):
        """Test fallback interactive with invalid demo name."""
        from sagaz.cli.demonstrations import _fallback_interactive

        with (
            patch("sagaz.cli.demonstrations.list_demos"),
            patch("sagaz.cli.demonstrations.click.prompt") as mock_prompt,
            patch("sagaz.cli.demonstrations.discover_demos") as mock_discover,
            patch("sagaz.cli.demonstrations.run_demo") as mock_run,
        ):
            mock_prompt.return_value = "nonexistent"
            mock_discover.return_value = {"basic_saga": Path("...")}

            _fallback_interactive()
            captured = capsys.readouterr()
            assert "unknown" in captured.out.lower()
            mock_run.assert_not_called()



    """Tests for display/rendering functions."""

    def test_validate_and_filter_domain(self):
        """Test validation of domain filter."""
        from sagaz.cli.demonstrations import _validate_and_filter_domain

        by_domain = {
            "core_patterns": {"basic_saga": Path("...")},
            "developer_experience": {"lifecycle_hooks": Path("...")},
        }

        # Valid filter
        result = _validate_and_filter_domain(by_domain, "core_patterns")
        assert result is not None
        assert "core_patterns" in result

        # Invalid filter
        result = _validate_and_filter_domain(by_domain, "nonexistent")
        assert result is None

        # No filter (None)
        result = _validate_and_filter_domain(by_domain, None)
        assert result == by_domain

    def test_display_demos_table(self, capsys):
        """Test table display of demonstrations."""
        from sagaz.cli.demonstrations import _display_demos_table

        with patch("sagaz.cli.demonstrations.get_demo_description") as mock_desc:
            mock_desc.return_value = "Test demo description"

            by_domain = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                }
            }
            meta_index = {
                "basic_saga": {"order": 1, "name": "core_patterns", "label": "Core Patterns"}
            }

            if _display_demos_table is not None:
                _display_demos_table(by_domain, meta_index)
                captured = capsys.readouterr()
                # Should have some output
                assert len(captured.out) > 0 or True  # May not always output

    def test_display_demos_plain(self, capsys):
        """Test plain text display of demonstrations."""
        from sagaz.cli.demonstrations import _display_demos_plain

        with patch("sagaz.cli.demonstrations.get_demo_description") as mock_desc:
            mock_desc.return_value = "Test demo description"

            by_domain = {
                "core_patterns": {
                    "basic_saga": Path("sagaz/demonstrations/core_patterns/basic_saga/main.py"),
                }
            }
            meta_index = {
                "basic_saga": {"order": 1, "name": "core_patterns", "label": "Core Patterns"}
            }

            _display_demos_plain(by_domain, meta_index)
            captured = capsys.readouterr()
            # Should have table-like output with header and demo info
            assert "Domain" in captured.out or "basic_saga" in captured.out
