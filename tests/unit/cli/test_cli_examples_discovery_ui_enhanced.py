import os
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from sagaz.cli.examples.discovery import (
    discover_examples,
    discover_examples_by_domain,
    get_categories,
    get_example_description,
    get_examples_dir,
)
from sagaz.cli.examples.ui import display_examples


class TestDiscoveryEnhanced:
    def test_get_examples_dir_fallbacks(self):
        with patch("importlib.resources.files", side_effect=ModuleNotFoundError):
            with patch("pathlib.Path.exists") as mock_exists:
                mock_exists.side_effect = [True]  # candidate exists
                d = get_examples_dir()
                assert "examples" in d.name

    def test_get_categories_empty(self):
        with patch("sagaz.cli.examples.discovery.get_examples_dir") as mock_dir:
            mock_dir.return_value = Path("/nonexistent")
            assert get_categories() == []

    def test_discover_examples_invalid_category(self):
        assert discover_examples("invalid_cat") == {}

    def test_get_example_description_variants(self, tmp_path):
        f1 = tmp_path / "f1.py"
        f1.write_text('"""Hello world"""\n')
        assert get_example_description(f1) == "Hello world"

        f2 = tmp_path / "f2.py"
        f2.write_text('"""\nMultiline\n"""\n')
        assert get_example_description(f2) == "Multiline"

        f3 = tmp_path / "f3.py"
        f3.write_text('#!/usr/bin/env python\n# some comment\nprint("hi")\n')
        assert get_example_description(f3) == "No description"


class TestUIEnhanced:
    def test_display_examples_plain(self, capsys):
        by_domain = {"Business": {"business/commerce/order": Path("/p1")}}
        with patch("sagaz.cli.examples.ui.console", None):
            with patch("sagaz.cli.examples.ui.get_example_description", return_value="Desc"):
                display_examples(by_domain)
                captured = capsys.readouterr()
                assert "Business" in captured.out
                assert "commerce" in captured.out
                assert "order" in captured.out
                assert "Desc" in captured.out

    def test_display_examples_table_branch(self):
        # Trigger the table branch
        by_domain = {"Business": {"business/commerce/order": Path("/p1")}}
        with patch("sagaz.cli.examples.ui.console") as mock_console:
            with patch("sagaz.cli.examples.ui.TableClass") as mock_table_cls:
                with patch("sagaz.cli.examples.ui.get_example_description", return_value="Desc"):
                    display_examples(by_domain)
                    mock_table_cls.assert_called()
                    mock_console.print.assert_called()
