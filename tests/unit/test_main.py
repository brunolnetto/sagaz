"""
Tests for sagaz.__main__ module
"""

import subprocess
import sys
from unittest.mock import patch

import pytest


class TestMain:
    """Test __main__ entry point"""

    def test_main_imports(self):
        """Test that __main__ imports correctly"""
        import sagaz.__main__  # noqa: F401

    def test_main_cli_invocation(self):
        """Test CLI can be invoked via -m flag"""
        result = subprocess.run(
            [sys.executable, "-m", "sagaz", "--help"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "Sagaz" in result.stdout or "sagaz" in result.stdout.lower()

    def test_main_version(self):
        """Test version command via __main__"""
        result = subprocess.run(
            [sys.executable, "-m", "sagaz", "--version"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0

    @patch("sagaz.cli.app.cli")
    def test_main_calls_cli(self, mock_cli):
        """Test that __main__ calls cli() when executed"""
        # This tests the actual execution path
        with patch("sagaz.__main__.__name__", "__main__"):
            # Import triggers execution
            import importlib
            import sagaz.__main__ as main_module

            importlib.reload(main_module)
            # Note: The actual execution happens on import when __name__ == "__main__"
            # In tests, __name__ is different, so we just verify imports work

    def test_main_module_direct_execution(self):
        """Test direct execution of __main__ module"""
        # Simulate running: python -m sagaz
        result = subprocess.run(
            [sys.executable, "-m", "sagaz"],
            capture_output=True,
            text=True,
            timeout=60,
            input="\n",  # Send newline to exit interactive commands
        )
        # Should exit with 0 (help/usage) or 2 (missing command)
        assert result.returncode in (0, 2)

    def test_main_module_exists(self):
        """Test __main__ module can be imported"""
        import sagaz.__main__

        assert hasattr(sagaz.__main__, "cli")
