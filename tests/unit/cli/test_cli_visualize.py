from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sagaz.cli.visualize import visualize_cmd


class DummySaga:
    def __init__(self):
        pass

    async def build(self):
        pass

    def to_mermaid(self, direction="TB"):
        return "graph TD;\n  A-->B;"


def test_visualize_invalid_path():
    runner = CliRunner()
    result = runner.invoke(visualize_cmd, ["invalid_path"])
    assert result.exit_code != 0
    assert "Invalid class path" in result.output


@patch("importlib.import_module")
def test_visualize_module_not_found(mock_import):
    mock_import.side_effect = ModuleNotFoundError("not found")
    runner = CliRunner()
    result = runner.invoke(visualize_cmd, ["pkg.mod:MySaga"])
    assert result.exit_code != 0
    assert "cannot import module" in result.output


@patch("importlib.import_module")
def test_visualize_class_not_found(mock_import):
    mock_mod = MagicMock()
    del mock_mod.MySaga
    mock_import.return_value = mock_mod
    runner = CliRunner()
    result = runner.invoke(visualize_cmd, ["pkg.mod:MySaga"])
    assert result.exit_code != 0
    assert "not found in" in result.output


@patch("importlib.import_module")
def test_visualize_success_mermaid(mock_import):
    mock_mod = MagicMock()
    mock_mod.MySaga = DummySaga
    mock_import.return_value = mock_mod
    runner = CliRunner()
    result = runner.invoke(visualize_cmd, ["pkg.mod:MySaga", "--format", "mermaid"])
    assert result.exit_code == 0
    assert "graph TD;" in result.output


@patch("importlib.import_module")
def test_visualize_success_markdown(mock_import):
    mock_mod = MagicMock()
    mock_mod.MySaga = DummySaga
    mock_import.return_value = mock_mod
    runner = CliRunner()
    result = runner.invoke(visualize_cmd, ["pkg.mod:MySaga", "--format", "markdown"])
    assert result.exit_code == 0
    assert "```mermaid\ngraph TD;\n  A-->B;\n```" in result.output


@patch("importlib.import_module")
def test_visualize_success_url(mock_import):
    mock_mod = MagicMock()
    mock_mod.MySaga = DummySaga
    mock_import.return_value = mock_mod
    runner = CliRunner()
    result = runner.invoke(visualize_cmd, ["pkg.mod:MySaga", "--format", "url"])
    assert result.exit_code == 0
    assert "https://mermaid.live/edit#base64:" in result.output


@patch("importlib.import_module")
def test_visualize_output_file(mock_import, tmp_path):
    mock_mod = MagicMock()
    mock_mod.MySaga = DummySaga
    mock_import.return_value = mock_mod
    runner = CliRunner()
    out_file = tmp_path / "out.md"
    result = runner.invoke(visualize_cmd, ["pkg.mod:MySaga", "--output", str(out_file)])
    assert result.exit_code == 0
    assert out_file.exists()
    assert "graph TD;" in out_file.read_text()


@patch("importlib.import_module")
def test_visualize_missing_to_mermaid(mock_import):
    class BadSaga:
        pass

    mock_mod = MagicMock()
    mock_mod.MySaga = BadSaga
    mock_import.return_value = mock_mod
    runner = CliRunner()
    result = runner.invoke(visualize_cmd, ["pkg.mod:MySaga"])
    assert result.exit_code != 0
    assert "does not have a to_mermaid() method" in result.output


@patch("importlib.import_module")
def test_visualize_init_error(mock_import):
    class ErrorSaga:
        def __init__(self):
            msg = "Init error"
            raise TypeError(msg)

        def to_mermaid(self):
            return ""

    mock_mod = MagicMock()
    mock_mod.MySaga = ErrorSaga
    mock_import.return_value = mock_mod
    runner = CliRunner()
    result = runner.invoke(visualize_cmd, ["pkg.mod:MySaga"])
    assert result.exit_code != 0
    assert "failed to instantiate MySaga" in result.output


@patch("importlib.import_module")
def test_visualize_build_error(mock_import):
    class BuildErrorSaga(DummySaga):
        async def build(self):
            msg = "Build failed"
            raise ValueError(msg)

    mock_mod = MagicMock()
    mock_mod.MySaga = BuildErrorSaga
    mock_import.return_value = mock_mod
    runner = CliRunner()
    result = runner.invoke(visualize_cmd, ["pkg.mod:MySaga"])
    assert result.exit_code == 0
    assert "Warning: build() raised ValueError" in result.output
