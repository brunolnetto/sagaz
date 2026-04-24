from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sagaz.cli.examples.interactive import (
    _category_menu_loop,
    _domain_category_menu_loop,
    _examples_menu_loop,
    _format_category_name,
    interactive_cmd,
)


class TestInteractiveExamples:
    def test_format_category_name(self):
        assert _format_category_name("iot") == "IoT"
        assert _format_category_name("ml") == "ML"
        assert _format_category_name("ai_agents") == "AI Agents"
        assert _format_category_name("order_processing") == "Order Processing"

    def test_interactive_cmd_fallback(self):
        with patch("sagaz.cli.examples.interactive.TERM_MENU_AVAILABLE", False):
            with patch("sagaz.cli.examples.interactive._fallback_interactive_simple") as mock_fallback:
                interactive_cmd("category")
                mock_fallback.assert_called_once_with("category")

    def test_category_menu_loop_with_domain_selection(self):
        with patch("sagaz.cli.examples.interactive.get_domains") as mock_domains:
            mock_domains.return_value = {"Business": ["commerce"]}
            with patch("sagaz.cli.examples.interactive.TerminalMenu") as mock_menu:
                mock_instance = mock_menu.return_value
                # Select "Business" (index 0), then "Exit" from category menu (index 2)
                # Then "Exit" from main menu (index 2)
                mock_instance.show.side_effect = [0, 2, 2]
                with patch("sagaz.cli.examples.interactive._domain_category_menu_loop", return_value="exit"):
                    _category_menu_loop()

    def test_domain_category_menu_loop_exit(self):
        with patch("sagaz.cli.examples.interactive.discover_examples", return_value={"ex1": Path("p1")}):
            with patch("sagaz.cli.examples.interactive.TerminalMenu") as mock_menu:
                mock_instance = mock_menu.return_value
                # Select "Exit" (index 3)
                mock_instance.show.return_value = 3
                result = _domain_category_menu_loop("Business", ["commerce"])
                assert result == "exit"

    def test_domain_category_menu_loop_nested_exit(self):
        with patch("sagaz.cli.examples.interactive.discover_examples", return_value={"ex1": Path("p1")}):
            with patch("sagaz.cli.examples.interactive.TerminalMenu") as mock_menu:
                mock_instance = mock_menu.return_value
                # Select "commerce" (index 0), which returns "exit"
                mock_instance.show.return_value = 0
                with patch("sagaz.cli.examples.interactive._examples_menu_loop", return_value="exit"):
                    result = _domain_category_menu_loop("Business", ["commerce"])
                    assert result == "exit"

    def test_prepare_example_menu_entries(self):
        from sagaz.cli.examples.interactive import _prepare_example_menu_entries
        sorted_ex = [("domain/cat/name", Path("script.py"))]
        with patch("sagaz.cli.examples.interactive.get_example_description", return_value="Desc"):
            entries = _prepare_example_menu_entries(sorted_ex)
            assert "▶ name" in entries[0]
            assert "Desc" in entries[0]

    def test_examples_menu_loop_back_and_exit(self):
        with patch("sagaz.cli.examples.interactive.discover_examples") as mock_discover:
            mock_discover.return_value = {"example1": Path("script.py")}
            with patch("sagaz.cli.examples.interactive.TerminalMenu") as mock_menu:
                mock_instance = mock_menu.return_value
                # Select "Back" (index 2)
                mock_instance.show.return_value = 2
                assert _examples_menu_loop("commerce") == "back"

                # Select "Exit" (index 3)
                mock_instance.show.return_value = 3
                assert _examples_menu_loop("commerce") == "exit"

    def test_interactive_cmd_with_category(self):
        with patch("sagaz.cli.examples.interactive._examples_menu_loop") as mock_loop:
            interactive_cmd("commerce")
            mock_loop.assert_called_once_with("commerce")

    def test_fallback_interactive_simple_no_examples(self, capsys):
        from sagaz.cli.examples.interactive import _fallback_interactive_simple
        with patch("sagaz.cli.examples.interactive.discover_examples", return_value={}):
            _fallback_interactive_simple()
            captured = capsys.readouterr()
            assert "No examples found." in captured.out
