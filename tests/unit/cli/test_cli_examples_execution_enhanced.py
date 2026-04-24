import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from sagaz.cli.examples.execution import (
    _check_package_installed,
    _check_requirements,
    _display_missing_packages,
    _parse_package_name,
    _prompt_user_continue,
    execute_example,
)


class TestExampleExecution:
    def test_execute_example_requirements_keyboard_interrupt(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("some-pkg")
        script = tmp_path / "script.py"

        with patch("sagaz.cli.examples.execution._check_requirements") as mock_check:
            mock_check.side_effect = KeyboardInterrupt
            with patch("sagaz.cli.examples.execution.console") as mock_console:
                execute_example(script)
                mock_console.print.assert_called_with("\n[yellow]Skipped example.[/yellow]")

    def test_execute_example_failed_with_requirements_hint(self, capsys):
        script = Path("script.py")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
            with patch("pathlib.Path.exists") as mock_exists:
                mock_exists.return_value = True  # Pretend requirements.txt exists
                execute_example(script)

                captured = capsys.readouterr()
                assert "Example failed with exit code 1" in captured.out
                assert "This example may require additional dependencies" in captured.out

    def test_check_requirements_file_read_error(self):
        # Should return silently if file cannot be opened
        with patch("pathlib.Path.open", side_effect=Exception):
            _check_requirements(Path("req.txt"))

    def test_check_requirements_missing_packages(self):
        with patch("pathlib.Path.open", mock_open(read_data="pkg1\npkg2")):
            with patch("sagaz.cli.examples.execution._check_package_installed") as mock_installed:
                mock_installed.side_effect = [False, True]
                with patch(
                    "sagaz.cli.examples.execution._display_missing_packages"
                ) as mock_display:
                    with patch("sagaz.cli.examples.execution._prompt_user_continue") as mock_prompt:
                        mock_prompt.return_value = True
                        _check_requirements(Path("req.txt"))
                        mock_display.assert_called_once_with(["pkg1"], Path("req.txt"))

    def test_check_requirements_abort_on_prompt(self):
        with patch("pathlib.Path.open", mock_open(read_data="pkg1")):
            with patch("sagaz.cli.examples.execution._check_package_installed", return_value=False):
                with patch(
                    "sagaz.cli.examples.execution._prompt_user_continue", return_value=False
                ):
                    with pytest.raises(KeyboardInterrupt):
                        _check_requirements(Path("req.txt"))

    def test_parse_package_name_variations(self):
        assert _parse_package_name("numpy>=1.2.0") == "numpy"
        assert _parse_package_name("pandas==1.5.0") == "pandas"
        assert _parse_package_name("scipy<2.0") == "scipy"
        assert _parse_package_name("torch>1.0") == "torch"

    def test_check_package_installed_mapping(self):
        with patch("importlib.util.find_spec") as mock_find:
            mock_find.return_value = MagicMock()
            assert _check_package_installed("python-dotenv") is True
            mock_find.assert_called_with("dotenv")

            assert _check_package_installed("pillow") is True
            mock_find.assert_called_with("PIL")

    def test_display_missing_packages_no_console(self, capsys):
        with patch("sagaz.cli.examples.execution.console", None):
            _display_missing_packages(["pkg1", "pkg2"], Path("req.txt"))
            captured = capsys.readouterr()
            assert "Missing dependencies: pkg1, pkg2" in captured.out

    def test_prompt_user_continue(self):
        with patch("builtins.input", return_value="y"):
            assert _prompt_user_continue() is True
        with patch("builtins.input", return_value="n"):
            assert _prompt_user_continue() is False
        with patch("builtins.input", return_value=""):
            assert _prompt_user_continue() is False
