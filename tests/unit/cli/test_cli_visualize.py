import base64
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sagaz.cli.visualize import visualize_cmd


@pytest.fixture
def runner():
    return CliRunner()


class MockSaga:
    def __init__(self):
        self.built = False

    async def build(self):
        self.built = True

    def to_mermaid(self, direction="TB"):
        return f"graph {direction}\nA --> B"


class MockSagaFailingBuild:
    async def build(self):
        msg = "Build failed"
        raise RuntimeError(msg)

    def to_mermaid(self, direction="TB"):
        return "graph TB\nBuildFailed"


class MockSagaNoMermaid:
    pass


class MockSagaInitFail:
    def __init__(self):
        msg = "Init failed"
        raise TypeError(msg)

    def to_mermaid(self, direction="TB"):
        return "graph TB"


def test_visualize_invalid_path(runner):
    result = runner.invoke(visualize_cmd, ["InvalidPath"])
    assert result.exit_code != 0
    assert "Invalid class path" in result.output


def test_visualize_module_not_found(runner):
    result = runner.invoke(visualize_cmd, ["nonexistent.module:Saga"])
    assert result.exit_code == 1
    assert "cannot import module" in result.output


def test_visualize_class_not_found(runner):
    # Use a real module but fake class
    result = runner.invoke(visualize_cmd, ["sagaz.cli.visualize:NonExistent"])
    assert result.exit_code == 1
    assert "class 'NonExistent' not found" in result.output


def test_visualize_no_to_mermaid(runner):
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MySaga = MockSagaNoMermaid
        mock_import.return_value = mock_module

        result = runner.invoke(visualize_cmd, ["myapp:MySaga"])
        assert result.exit_code == 1
        assert "does not have a to_mermaid() method" in result.output


def test_visualize_instantiation_failure(runner):
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MySaga = MockSagaInitFail
        mock_import.return_value = mock_module

        result = runner.invoke(visualize_cmd, ["myapp:MySaga"])
        assert result.exit_code == 1
        assert "failed to instantiate MySaga" in result.output


def test_visualize_build_failure_warning(runner):
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MySaga = MockSagaFailingBuild
        mock_import.return_value = mock_module

        result = runner.invoke(visualize_cmd, ["myapp:MySaga"])
        assert result.exit_code == 0
        assert "Warning: build() raised RuntimeError" in result.output
        assert "BuildFailed" in result.output


def test_visualize_success_mermaid(runner):
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MySaga = MockSaga
        mock_import.return_value = mock_module

        result = runner.invoke(visualize_cmd, ["myapp:MySaga"])
        assert result.exit_code == 0
        assert "graph TB" in result.output
        assert "A --> B" in result.output


def test_visualize_success_markdown(runner):
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MySaga = MockSaga
        mock_import.return_value = mock_module

        result = runner.invoke(visualize_cmd, ["myapp:MySaga", "--format", "markdown"])
        assert result.exit_code == 0
        assert "```mermaid" in result.output
        assert "graph TB" in result.output


def test_visualize_success_url(runner):
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MySaga = MockSaga
        mock_import.return_value = mock_module

        result = runner.invoke(visualize_cmd, ["myapp:MySaga", "--format", "url"])
        assert result.exit_code == 0
        assert "https://mermaid.live/edit#base64:" in result.output

        # Verify base64 content
        encoded = result.output.split("base64:")[1].strip()
        decoded = base64.urlsafe_b64decode(encoded).decode()
        assert "graph TB" in decoded


def test_visualize_output_to_file(runner, tmp_path):
    output_file = tmp_path / "diagram.mmd"
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MySaga = MockSaga
        mock_import.return_value = mock_module

        result = runner.invoke(visualize_cmd, ["myapp:MySaga", "--output", str(output_file)])
        assert result.exit_code == 0
        assert output_file.exists()
        assert "graph TB" in output_file.read_text()


def test_visualize_direction(runner):
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MySaga = MockSaga
        mock_import.return_value = mock_module

        result = runner.invoke(visualize_cmd, ["myapp:MySaga", "--direction", "LR"])
        assert result.exit_code == 0
        assert "graph LR" in result.output
