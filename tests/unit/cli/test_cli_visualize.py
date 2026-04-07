"""
Tests for the sagaz visualize CLI command.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from sagaz.cli.app import visualize_cmd

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_saga_cls(mermaid_output: str = "flowchart TB\n  A --> B") -> type:
    """Return a fake Saga class whose build() and to_mermaid() return predictably."""

    class FakeSaga:
        async def build(self) -> None:
            pass

        def to_mermaid(
            self,
            direction: str = "TB",
            show_compensation: bool = True,
            **kwargs,
        ) -> str:
            return mermaid_output

    return FakeSaga


_DUMMY_IMPORT_PATH = "tests.unit.cli.test_cli_visualize:_dummy_saga"


# ---------------------------------------------------------------------------
# Tests — argument / option parsing
# ---------------------------------------------------------------------------


class TestVisualizeArgParsing:
    def test_missing_colon_gives_usage_error(self):
        runner = CliRunner()
        result = runner.invoke(visualize_cmd, ["my.module.ClassName"])
        assert result.exit_code != 0

    def test_nonexistent_module_exits_nonzero(self):
        runner = CliRunner()
        result = runner.invoke(visualize_cmd, ["nonexistent.module:SomeClass"])
        assert result.exit_code != 0

    def test_missing_class_exits_nonzero(self, tmp_path):
        runner = CliRunner()
        with patch("importlib.import_module") as mock_import:
            mock_import.return_value = MagicMock(spec=[])  # no SomeClass attribute
            result = runner.invoke(visualize_cmd, ["mymodule:MissingClass"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Tests — output formats
# ---------------------------------------------------------------------------


class TestVisualizeOutputFormats:
    def _invoke(self, *args: str) -> CliRunner:
        from click.testing import CliRunner

        runner = CliRunner()
        cls = _make_saga_cls()
        with patch("importlib.import_module") as mock_import:
            module = MagicMock()
            module.MySaga = cls
            mock_import.return_value = module
            return runner.invoke(visualize_cmd, ["mymod:MySaga", *args])

    def test_default_format_is_mermaid(self):
        result = self._invoke()
        assert result.exit_code == 0
        assert "flowchart" in result.output

    def test_markdown_format_wraps_in_fences(self):
        result = self._invoke("--format", "markdown")
        assert result.exit_code == 0
        assert "```mermaid" in result.output

    def test_url_format_generates_mermaid_live_url(self):
        result = self._invoke("--format", "url")
        assert result.exit_code == 0
        assert "mermaid.live/edit#base64:" in result.output

    def test_output_file_writes_to_disk(self, tmp_path):
        out = tmp_path / "diagram.md"
        runner = CliRunner()
        cls = _make_saga_cls()
        with patch("importlib.import_module") as mock_import:
            module = MagicMock()
            module.MySaga = cls
            mock_import.return_value = module
            result = runner.invoke(
                visualize_cmd,
                ["mymod:MySaga", "--format", "markdown", "--output", str(out)],
            )
        assert result.exit_code == 0
        assert out.exists()
        assert "```mermaid" in out.read_text()

    def test_direction_lr_is_forwarded(self):
        runner = CliRunner()
        received_direction = []

        class DirCaptureSaga:
            async def build(self) -> None:
                pass

            def to_mermaid(self, direction: str = "TB", **kwargs) -> str:
                received_direction.append(direction)
                return "flowchart LR\n  A --> B"

        with patch("importlib.import_module") as mock_import:
            module = MagicMock()
            module.MySaga = DirCaptureSaga
            mock_import.return_value = module
            runner.invoke(visualize_cmd, ["mymod:MySaga", "--direction", "LR"])

        assert received_direction == ["LR"]


# ---------------------------------------------------------------------------
# Tests — build() error resilience
# ---------------------------------------------------------------------------


class TestVisualizeBuildErrors:
    def test_build_exception_is_warned_but_continues(self):
        class BrokenBuildSaga:
            async def build(self) -> None:
                msg = "external dependency unavailable"
                raise RuntimeError(msg)

            def to_mermaid(self, **kwargs) -> str:
                return "flowchart TB\n  A --> B"

        runner = CliRunner()
        with patch("importlib.import_module") as mock_import:
            module = MagicMock()
            module.MySaga = BrokenBuildSaga
            mock_import.return_value = module
            result = runner.invoke(visualize_cmd, ["mymod:MySaga"])

        # Still produces output (diagram is empty but doesn't crash)
        assert result.exit_code == 0

    def test_class_without_to_mermaid_exits_nonzero(self):
        class NotASaga:
            async def build(self) -> None:
                pass

        runner = CliRunner()
        with patch("importlib.import_module") as mock_import:
            module = MagicMock()
            module.MySaga = NotASaga
            mock_import.return_value = module
            result = runner.invoke(visualize_cmd, ["mymod:MySaga"])

        assert result.exit_code != 0

    def test_constructor_requires_args_exits_nonzero(self):
        class RequiresArgsSaga:
            def __init__(self, required_arg: str) -> None:
                self._arg = required_arg

            async def build(self) -> None:
                pass

            def to_mermaid(self, **kwargs) -> str:
                return "flowchart TB\n  A"

        runner = CliRunner()
        with patch("importlib.import_module") as mock_import:
            module = MagicMock()
            module.MySaga = RequiresArgsSaga
            mock_import.return_value = module
            result = runner.invoke(visualize_cmd, ["mymod:MySaga"])

        assert result.exit_code != 0
