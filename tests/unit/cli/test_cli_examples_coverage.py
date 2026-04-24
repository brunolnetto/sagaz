"""
Additional coverage tests for cli_examples.py.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sagaz.cli.examples import execute_example, list_examples_cmd


def test_list_examples_no_console(capsys):
    """Test list_examples_cmd fallback when rich console is missing."""
    with (
        patch("sagaz.cli.examples.ui.console", None),
        patch("sagaz.cli.examples.ui.TableClass", None),
        patch("sagaz.cli.examples.discover_examples_by_domain") as mock_discover,
    ):
        mock_discover.return_value = {
            "business": {"business/commerce/order_processing": Path("/path/to/example1/main.py")}
        }

        list_examples_cmd()

        captured = capsys.readouterr()
        # Check for table header format (plain text display)
        assert "Domain" in captured.out
        assert "Subdomain" in captured.out
        assert "Name" in captured.out
        assert "Description" in captured.out
        assert "order_processing" in captured.out


def testexecute_example_pythonpath():
    """Test execute_example sets PYTHONPATH correctly."""
    with patch("subprocess.run") as mock_run, patch("os.environ.copy") as mock_env_copy:
        mock_env = {"EXISTING": "val"}
        mock_env_copy.return_value = mock_env

        execute_example(Path("script.py"))

        # Verify PYTHONPATH was set
        call_kwargs = mock_run.call_args[1]
        env_arg = call_kwargs["env"]
        assert "PYTHONPATH" in env_arg
        assert str(Path.cwd()) in env_arg["PYTHONPATH"]


def testexecute_example_extending_pythonpath():
    """Test execute_example extends existing PYTHONPATH."""
    with patch("subprocess.run") as mock_run, patch("os.environ.copy") as mock_env_copy:
        mock_env = {"PYTHONPATH": "/existing/path"}
        mock_env_copy.return_value = mock_env

        execute_example(Path("script.py"))

        # Verify PYTHONPATH was extended
        call_kwargs = mock_run.call_args[1]
        env_arg = call_kwargs["env"]
        assert "/existing/path" in env_arg["PYTHONPATH"]
        assert str(Path.cwd()) in env_arg["PYTHONPATH"]
