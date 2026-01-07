
"""
Additional coverage tests for cli_examples.py.
"""
import pytest
from unittest.mock import patch, MagicMock
from sagaz.cli_examples import list_examples_cmd, _execute_example
from pathlib import Path

def test_list_examples_no_console(capsys):
    """Test list_examples_cmd fallback when rich console is missing."""
    with patch("sagaz.cli_examples.console", None), \
         patch("sagaz.cli_examples.Table", None), \
         patch("sagaz.cli_examples.discover_examples") as mock_discover:
        
        mock_discover.return_value = {
            "example1": Path("/path/to/example1/main.py")
        }
        
        list_examples_cmd()
        
        captured = capsys.readouterr()
        assert "Available Examples:" in captured.out
        assert "- example1" in captured.out

def test_execute_example_pythonpath():
    """Test _execute_example sets PYTHONPATH correctly."""
    with patch("subprocess.run") as mock_run, \
         patch("os.environ.copy") as mock_env_copy:
        
        mock_env = {"EXISTING": "val"}
        mock_env_copy.return_value = mock_env
        
        _execute_example(Path("script.py"))
        
        # Verify PYTHONPATH was set
        call_kwargs = mock_run.call_args[1]
        env_arg = call_kwargs["env"]
        assert "PYTHONPATH" in env_arg
        assert str(Path.cwd()) in env_arg["PYTHONPATH"]

def test_execute_example_extending_pythonpath():
    """Test _execute_example extends existing PYTHONPATH."""
    with patch("subprocess.run") as mock_run, \
         patch("os.environ.copy") as mock_env_copy:
        
        mock_env = {"PYTHONPATH": "/existing/path"}
        mock_env_copy.return_value = mock_env
        
        _execute_example(Path("script.py"))
        
        # Verify PYTHONPATH was extended
        call_kwargs = mock_run.call_args[1]
        env_arg = call_kwargs["env"]
        assert "/existing/path" in env_arg["PYTHONPATH"]
        assert str(Path.cwd()) in env_arg["PYTHONPATH"]

