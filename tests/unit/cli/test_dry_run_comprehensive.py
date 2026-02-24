"""
Comprehensive tests for dry_run CLI module to achieve 95%+ coverage.

Tests all uncovered paths including:
- Interactive selection flows
- Error paths in discovery
- Plain text output formatting
- Edge cases in validation/simulation
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import yaml
from click.testing import CliRunner

from sagaz.cli.dry_run import (
    _discover_and_select_sagas,
    _discover_project_sagas,
    _discover_sagas_in_directory,
    _discover_sagas_in_paths,
    _display_project_simulation_results_plain,
    _display_project_validation_results_plain,
    _display_simulation_results,
    _display_validation_results,
    _extract_sagas_from_module,
    _interactive_saga_selection,
    _run_simulation_for_sagas,
    _run_validation_for_sagas,
    _try_load_sagas_from_file,
    simulate_cmd,
    validate_cmd,
)
from sagaz.dry_run import DryRunMode, DryRunResult


@pytest.fixture
def temp_project_with_sagas(tmp_path):
    """Create a temporary project with sagas."""
    config = {
        "version": "1.0",
        "project": {"name": "test-project"},
        "paths": ["sagas/"],
    }
    (tmp_path / "sagaz.yaml").write_text(yaml.dump(config))

    sagas_dir = tmp_path / "sagas"
    sagas_dir.mkdir()

    saga_code = '''"""Test saga."""
from sagaz import Saga, action

class TestSaga(Saga):
    """Test saga."""
    
    @action
    async def step_one(self, context):
        """First step."""
        return {"result": "ok"}
    
    @action
    async def step_two(self, context):
        """Second step."""
        return {"result": "ok"}
'''
    (sagas_dir / "test_saga.py").write_text(saga_code)
    
    return tmp_path


@pytest.fixture
def multiple_sagas_project(tmp_path):
    """Create project with multiple sagas."""
    config = {
        "version": "1.0",
        "project": {"name": "multi-saga-project"},
        "paths": ["sagas/"],
    }
    (tmp_path / "sagaz.yaml").write_text(yaml.dump(config))

    sagas_dir = tmp_path / "sagas"
    sagas_dir.mkdir()

    for i in range(3):
        saga_code = f'''"""Test saga {i}."""
from sagaz import Saga, action

class TestSaga{i}(Saga):
    """Test saga {i}."""
    
    @action
    async def step_one(self, context):
        return {{"result": "ok"}}
'''
        (sagas_dir / f"test_saga_{i}.py").write_text(saga_code)
    
    return tmp_path


class TestInteractiveSagaSelection:
    """Tests for interactive saga selection."""

    def test_single_saga_auto_selects(self, capsys):
        """Test that single saga is auto-selected."""
        sagas = [{"name": "SingleSaga", "file": "test.py"}]
        
        with patch("sagaz.cli.dry_run.RICH_AVAILABLE", False):
            result = _interactive_saga_selection(sagas, "validate")
        
        assert result == "SingleSaga"
        captured = capsys.readouterr()
        assert "Auto-selecting" in captured.out

    def test_single_saga_with_rich(self, capsys):
        """Test single saga selection with rich available."""
        sagas = [{"name": "SingleSaga", "file": "test.py"}]
        
        with patch("sagaz.cli.dry_run.RICH_AVAILABLE", True), \
             patch("sagaz.cli.dry_run.console") as mock_console:
            result = _interactive_saga_selection(sagas, "validate")
        
        assert result == "SingleSaga"
        mock_console.print.assert_called()

    def test_empty_sagas_list(self):
        """Test with empty sagas list."""
        result = _interactive_saga_selection([], "validate")
        assert result is None

    def test_user_cancels_selection(self, monkeypatch):
        """Test user cancelling selection."""
        sagas = [
            {"name": "Saga1", "file": "s1.py"},
            {"name": "Saga2", "file": "s2.py"},
        ]
        
        monkeypatch.setattr("click.prompt", lambda *args, **kwargs: 0)
        
        result = _interactive_saga_selection(sagas, "validate")
        assert result is None

    def test_user_selects_second_saga(self, monkeypatch):
        """Test user selecting a specific saga."""
        sagas = [
            {"name": "Saga1", "file": "s1.py"},
            {"name": "Saga2", "file": "s2.py"},
            {"name": "Saga3", "file": "s3.py"},
        ]
        
        monkeypatch.setattr("click.prompt", lambda *args, **kwargs: 2)
        
        result = _interactive_saga_selection(sagas, "simulate")
        assert result == "Saga2"


class TestDiscoverProjectSagas:
    """Tests for saga discovery."""

    def test_no_config_file(self, tmp_path, monkeypatch):
        """Test when sagaz.yaml doesn't exist."""
        monkeypatch.chdir(tmp_path)
        result = _discover_project_sagas()
        assert result == []

    def test_invalid_yaml(self, tmp_path, monkeypatch):
        """Test with invalid YAML file."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "sagaz.yaml").write_text("invalid: yaml: content: {{")
        
        result = _discover_project_sagas()
        assert result == []

    def test_missing_paths_uses_default(self, tmp_path, monkeypatch):
        """Test default paths when not specified."""
        monkeypatch.chdir(tmp_path)
        config = {"version": "1.0", "project": {"name": "test"}}
        (tmp_path / "sagaz.yaml").write_text(yaml.dump(config))
        
        sagas_dir = tmp_path / "sagas"
        sagas_dir.mkdir()
        
        with patch("sagaz.cli.dry_run._discover_sagas_in_paths") as mock_discover:
            mock_discover.return_value = []
            _discover_project_sagas()
            mock_discover.assert_called_once_with(["sagas/"])


class TestDiscoverSagasInPaths:
    """Tests for discovering sagas in specific paths."""

    def test_nonexistent_path(self):
        """Test with nonexistent path."""
        result = _discover_sagas_in_paths(["/nonexistent/path"])
        assert result == []

    def test_multiple_paths(self, tmp_path):
        """Test discovering from multiple paths."""
        path1 = tmp_path / "path1"
        path2 = tmp_path / "path2"
        path1.mkdir()
        path2.mkdir()
        
        saga_code = '''from sagaz import Saga, action
class MySaga(Saga):
    @action
    async def step(self, ctx):
        pass
'''
        (path1 / "saga1.py").write_text(saga_code)
        (path2 / "saga2.py").write_text(saga_code)
        
        result = _discover_sagas_in_paths([str(path1), str(path2)])
        assert len(result) == 2


class TestDiscoverSagasInDirectory:
    """Tests for discovering sagas in a directory."""

    def test_ignores_dunder_files(self, tmp_path):
        """Test that __init__.py and similar are ignored."""
        (tmp_path / "__init__.py").write_text("# init file")
        (tmp_path / "__pycache__").mkdir()
        
        import importlib
        import inspect
        from sagaz import Saga
        
        result = _discover_sagas_in_directory(tmp_path, sys, importlib, inspect, Saga)
        assert result == []

    def test_recursive_discovery(self, tmp_path):
        """Test recursive directory traversal."""
        subdir = tmp_path / "sub" / "nested"
        subdir.mkdir(parents=True)
        
        saga_code = '''from sagaz import Saga, action
class DeepSaga(Saga):
    @action
    async def step(self, ctx):
        pass
'''
        (subdir / "deep_saga.py").write_text(saga_code)
        
        import importlib
        import inspect
        from sagaz import Saga
        
        result = _discover_sagas_in_directory(tmp_path, sys, importlib, inspect, Saga)
        assert len(result) == 1
        assert result[0]["name"] == "DeepSaga"


class TestTryLoadSagasFromFile:
    """Tests for loading sagas from files."""

    def test_invalid_python_file(self, tmp_path):
        """Test with syntactically invalid Python."""
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def invalid syntax here")
        
        import importlib
        import inspect
        from sagaz import Saga
        
        result = _try_load_sagas_from_file(bad_file, sys, importlib, inspect, Saga)
        assert result == []

    def test_file_without_sagas(self, tmp_path):
        """Test Python file with no Saga classes."""
        regular_file = tmp_path / "regular.py"
        regular_file.write_text("""
class RegularClass:
    pass

def some_function():
    pass
""")
        
        import importlib
        import inspect
        from sagaz import Saga
        
        result = _try_load_sagas_from_file(regular_file, sys, importlib, inspect, Saga)
        assert result == []

    def test_file_with_import_error(self, tmp_path):
        """Test file that raises ImportError."""
        error_file = tmp_path / "error.py"
        error_file.write_text("import nonexistent_module\nclass Test: pass")
        
        import importlib
        import inspect
        from sagaz import Saga
        
        result = _try_load_sagas_from_file(error_file, sys, importlib, inspect, Saga)
        assert result == []


class TestExtractSagasFromModule:
    """Tests for extracting Saga classes from modules."""

    def test_ignores_base_saga_class(self):
        """Test that base Saga class is not extracted."""
        import inspect
        from sagaz import Saga
        
        module = type(sys)("test_module")
        module.Saga = Saga
        
        result = _extract_sagas_from_module(module, Path("test.py"), inspect, Saga)
        assert result == []

    def test_extracts_saga_subclasses(self):
        """Test extraction of actual saga subclasses."""
        import inspect
        from sagaz import Saga
        
        module = type(sys)("test_module")
        
        class MySaga(Saga):
            pass
        
        class AnotherSaga(Saga):
            pass
        
        module.MySaga = MySaga
        module.AnotherSaga = AnotherSaga
        module.NotASaga = str
        
        result = _extract_sagas_from_module(module, Path("test.py"), inspect, Saga)
        assert len(result) == 2
        names = [s["name"] for s in result]
        assert "MySaga" in names
        assert "AnotherSaga" in names


class TestDiscoverAndSelectSagas:
    """Tests for the main discovery and selection function."""

    def test_no_sagas_found_exits(self):
        """Test that missing sagas causes exit."""
        with patch("sagaz.cli.dry_run._discover_project_sagas", return_value=[]), \
             pytest.raises(SystemExit) as exc_info:
            _discover_and_select_sagas(None, "validate", False)
        
        assert exc_info.value.code == 1

    def test_specific_saga_not_found(self):
        """Test requesting nonexistent saga."""
        sagas = [{"name": "ExistingSaga", "file": "test.py"}]
        
        with patch("sagaz.cli.dry_run._discover_project_sagas", return_value=sagas), \
             pytest.raises(SystemExit) as exc_info:
            _discover_and_select_sagas("NonexistentSaga", "validate", False)
        
        assert exc_info.value.code == 1

    def test_specific_saga_found(self):
        """Test finding specific saga by name."""
        sagas = [
            {"name": "Saga1", "file": "s1.py"},
            {"name": "Saga2", "file": "s2.py"},
        ]
        
        with patch("sagaz.cli.dry_run._discover_project_sagas", return_value=sagas):
            result = _discover_and_select_sagas("Saga2", "validate", False)
        
        assert len(result) == 1
        assert result[0]["name"] == "Saga2"

    def test_interactive_cancelled(self):
        """Test interactive selection cancelled by user."""
        sagas = [{"name": "Saga1", "file": "s1.py"}]
        
        with patch("sagaz.cli.dry_run._discover_project_sagas", return_value=sagas), \
             patch("sagaz.cli.dry_run._interactive_saga_selection", return_value=None), \
             pytest.raises(SystemExit) as exc_info:
            _discover_and_select_sagas(None, "validate", interactive=True)
        
        assert exc_info.value.code == 0

    def test_all_sagas_returned_by_default(self):
        """Test that all sagas are returned when no filter."""
        sagas = [
            {"name": "Saga1", "file": "s1.py"},
            {"name": "Saga2", "file": "s2.py"},
        ]
        
        with patch("sagaz.cli.dry_run._discover_project_sagas", return_value=sagas):
            result = _discover_and_select_sagas(None, "validate", False)
        
        assert len(result) == 2


class TestRunValidationForSagas:
    """Tests for validation execution."""

    def test_validates_all_sagas(self):
        """Test validation runs for all provided sagas."""
        from sagaz import Saga, action
        
        class MockSaga(Saga):
            @action
            async def step(self, ctx):
                return {"ok": True}
        
        sagas = [
            {"name": "Saga1", "class": MockSaga},
            {"name": "Saga2", "class": MockSaga},
        ]
        
        mock_result = DryRunResult(
            mode=DryRunMode.VALIDATE,
            success=True
        )
        
        with patch("sagaz.cli.dry_run.DryRunEngine") as mock_engine:
            mock_instance = Mock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            mock_engine.return_value = mock_instance
            
            results = _run_validation_for_sagas(sagas, {})
        
        assert len(results) == 2
        assert results[0][0] == "Saga1"
        assert results[1][0] == "Saga2"


class TestRunSimulationForSagas:
    """Tests for simulation execution."""

    def test_simulates_all_sagas(self):
        """Test simulation runs for all provided sagas."""
        from sagaz import Saga, action
        
        class MockSaga(Saga):
            @action
            async def step(self, ctx):
                return {"ok": True}
        
        sagas = [
            {"name": "Saga1", "class": MockSaga},
        ]
        
        mock_result = DryRunResult(
            mode=DryRunMode.VALIDATE,
            success=True
        )
        
        with patch("sagaz.cli.dry_run.DryRunEngine") as mock_engine:
            mock_instance = Mock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            mock_engine.return_value = mock_instance
            
            results = _run_simulation_for_sagas(sagas, {"test": "context"})
        
        assert len(results) == 1


class TestDisplayValidationResults:
    """Tests for validation result display."""

    def test_uses_rich_when_available(self):
        """Test Rich output is used when available."""
        results = []
        
        with patch("sagaz.cli.dry_run.RICH_AVAILABLE", True), \
             patch("sagaz.cli.dry_run._display_project_validation_results_rich") as mock_rich:
            _display_validation_results(results)
            mock_rich.assert_called_once_with(results)

    def test_uses_plain_when_rich_unavailable(self):
        """Test plain output when Rich not available."""
        results = []
        
        with patch("sagaz.cli.dry_run.RICH_AVAILABLE", False), \
             patch("sagaz.cli.dry_run._display_project_validation_results_plain") as mock_plain:
            _display_validation_results(results)
            mock_plain.assert_called_once_with(results)


class TestDisplaySimulationResults:
    """Tests for simulation result display."""

    def test_uses_rich_when_available(self):
        """Test Rich output for simulation."""
        results = []
        
        with patch("sagaz.cli.dry_run.RICH_AVAILABLE", True), \
             patch("sagaz.cli.dry_run._display_project_simulation_results_rich") as mock_rich:
            _display_simulation_results(results, show_parallel=False)
            mock_rich.assert_called_once_with(results, False)

    def test_uses_plain_when_rich_unavailable(self):
        """Test plain output for simulation."""
        results = []
        
        with patch("sagaz.cli.dry_run.RICH_AVAILABLE", False), \
             patch("sagaz.cli.dry_run._display_project_simulation_results_plain") as mock_plain:
            _display_simulation_results(results, show_parallel=True)
            mock_plain.assert_called_once_with(results, True)


class TestPlainTextOutputFormatting:
    """Tests for plain text output functions."""

    def test_validation_results_plain_success(self):
        """Test plain text validation output for success."""
        mock_result = DryRunResult(
            mode=DryRunMode.VALIDATE,
            success=True,
            execution_order=["step1", "step2"]
        )
        results = [("TestSaga", mock_result)]
        
        # Should not raise errors
        _display_project_validation_results_plain(results)

    def test_validation_results_plain_with_errors(self):
        """Test plain text validation output with errors."""
        mock_result = DryRunResult(
            mode=DryRunMode.VALIDATE,
            success=False,
            validation_errors=["Error 1", "Error 2"],
            validation_warnings=["Warning 1"]
        )
        results = [("FailingSaga", mock_result)]
        
        # Should not raise errors
        _display_project_validation_results_plain(results)

    def test_simulation_results_plain_basic(self):
        """Test plain text simulation output."""
        mock_result = DryRunResult(
            mode=DryRunMode.VALIDATE,
            success=True,
            execution_order=["step_one", "step_two"],
            metadata={"step_count": 2}
        )
        results = [("SimSaga", mock_result)]
        
        # Should not raise errors
        _display_project_simulation_results_plain(results, show_parallel=False)

    def test_simulation_results_plain_with_parallel(self):
        """Test plain text simulation with parallel groups."""
        mock_result = DryRunResult(
            mode=DryRunMode.VALIDATE,
            success=True,
            execution_order=["step1", "step2"],
            metadata={"parallel_groups": [[("step1", 0)], [("step2", 1)]]}
        )
        results = [("ParallelSaga", mock_result)]
        
        # Should not raise errors
        _display_project_simulation_results_plain(results, show_parallel=True)


class TestValidateCommand:
    """Tests for validate CLI command."""

    def test_validate_all_sagas_success(self, temp_project_with_sagas, monkeypatch):
        """Test validating all sagas successfully."""
        monkeypatch.chdir(temp_project_with_sagas)
        runner = CliRunner()
        
        with patch("sagaz.cli.dry_run._discover_project_sagas") as mock_discover, \
             patch("sagaz.cli.dry_run._run_validation_for_sagas") as mock_run, \
             patch("sagaz.cli.dry_run._display_validation_results"):
            mock_discover.return_value = [{"name": "TestSaga", "class": Mock}]
            mock_run.return_value = [("TestSaga", DryRunResult(mode=DryRunMode.VALIDATE, success=True))]
            result = runner.invoke(validate_cmd, ["--context", "{}"])
        
        assert result.exit_code == 0

    def test_validate_specific_saga(self, temp_project_with_sagas, monkeypatch):
        """Test validating specific saga."""
        monkeypatch.chdir(temp_project_with_sagas)
        runner = CliRunner()
        
        with patch("sagaz.cli.dry_run._discover_project_sagas") as mock_discover, \
             patch("sagaz.cli.dry_run._run_validation_for_sagas") as mock_run, \
             patch("sagaz.cli.dry_run._display_validation_results"):
            mock_discover.return_value = [{"name": "TestSaga", "class": Mock}]
            mock_run.return_value = [("TestSaga", DryRunResult(mode=DryRunMode.VALIDATE, success=True))]
            result = runner.invoke(validate_cmd, ["--saga", "TestSaga", "--context", "{}"])
        
        assert result.exit_code == 0

    def test_validate_with_context(self, temp_project_with_sagas, monkeypatch):
        """Test validation with custom context."""
        monkeypatch.chdir(temp_project_with_sagas)
        runner = CliRunner()
        
        context = json.dumps({"test_key": "test_value"})
        with patch("sagaz.cli.dry_run._discover_project_sagas") as mock_discover, \
             patch("sagaz.cli.dry_run._run_validation_for_sagas") as mock_run, \
             patch("sagaz.cli.dry_run._display_validation_results"):
            mock_discover.return_value = [{"name": "TestSaga", "class": Mock}]
            mock_run.return_value = [("TestSaga", DryRunResult(mode=DryRunMode.VALIDATE, success=True))]
            result = runner.invoke(validate_cmd, ["--context", context])
        
        assert result.exit_code == 0

    def test_validate_nonexistent_saga(self, temp_project_with_sagas, monkeypatch):
        """Test validating nonexistent saga."""
        monkeypatch.chdir(temp_project_with_sagas)
        runner = CliRunner()
        
        with patch("sagaz.cli.dry_run._discover_project_sagas") as mock_discover:
            mock_discover.return_value = [{"name": "OtherSaga", "class": Mock}]
            result = runner.invoke(validate_cmd, ["--saga", "NonexistentSaga"])
        
        assert result.exit_code == 1

    def test_validate_interactive_mode(self, multiple_sagas_project, monkeypatch):
        """Test interactive validation mode."""
        monkeypatch.chdir(multiple_sagas_project)
        runner = CliRunner()
        
        with patch("sagaz.cli.dry_run._discover_project_sagas") as mock_discover, \
             patch("sagaz.cli.dry_run._interactive_saga_selection") as mock_interactive, \
             patch("sagaz.cli.dry_run._run_validation_for_sagas") as mock_run, \
             patch("sagaz.cli.dry_run._display_validation_results"):
            mock_discover.return_value = [{"name": "TestSaga0", "class": Mock}]
            mock_interactive.return_value = "TestSaga0"
            mock_run.return_value = [("TestSaga0", DryRunResult(mode=DryRunMode.VALIDATE, success=True))]
            result = runner.invoke(validate_cmd, ["--interactive"], input="1\n")
        
        assert result.exit_code == 0


class TestSimulateCommand:
    """Tests for simulate CLI command."""

    def test_simulate_all_sagas(self, temp_project_with_sagas, monkeypatch):
        """Test simulating all sagas."""
        monkeypatch.chdir(temp_project_with_sagas)
        runner = CliRunner()
        
        with patch("sagaz.cli.dry_run._discover_project_sagas") as mock_discover, \
             patch("sagaz.cli.dry_run._run_simulation_for_sagas") as mock_run, \
             patch("sagaz.cli.dry_run._display_simulation_results"):
            mock_discover.return_value = [{"name": "TestSaga", "class": Mock}]
            mock_run.return_value = [("TestSaga", DryRunResult(mode=DryRunMode.SIMULATE, success=True))]
            result = runner.invoke(simulate_cmd, ["--context", "{}"])
        
        assert result.exit_code == 0

    def test_simulate_with_parallel_flag(self, temp_project_with_sagas, monkeypatch):
        """Test simulation with parallel execution display."""
        monkeypatch.chdir(temp_project_with_sagas)
        runner = CliRunner()
        
        with patch("sagaz.cli.dry_run._discover_project_sagas") as mock_discover, \
             patch("sagaz.cli.dry_run._run_simulation_for_sagas") as mock_run, \
             patch("sagaz.cli.dry_run._display_simulation_results"):
            mock_discover.return_value = [{"name": "TestSaga", "class": Mock}]
            mock_run.return_value = [("TestSaga", DryRunResult(mode=DryRunMode.SIMULATE, success=True))]
            result = runner.invoke(simulate_cmd, ["--show-parallel"])
        
        assert result.exit_code == 0

    def test_simulate_specific_saga(self, temp_project_with_sagas, monkeypatch):
        """Test simulating specific saga."""
        monkeypatch.chdir(temp_project_with_sagas)
        runner = CliRunner()
        
        with patch("sagaz.cli.dry_run._discover_project_sagas") as mock_discover, \
             patch("sagaz.cli.dry_run._run_simulation_for_sagas") as mock_run, \
             patch("sagaz.cli.dry_run._display_simulation_results"):
            mock_discover.return_value = [{"name": "TestSaga", "class": Mock}]
            mock_run.return_value = [("TestSaga", DryRunResult(mode=DryRunMode.SIMULATE, success=True))]
            result = runner.invoke(simulate_cmd, ["--saga", "TestSaga"])
        
        assert result.exit_code == 0

    def test_simulate_interactive_mode(self, multiple_sagas_project, monkeypatch):
        """Test interactive simulation mode."""
        monkeypatch.chdir(multiple_sagas_project)
        runner = CliRunner()
        
        with patch("sagaz.cli.dry_run._discover_project_sagas") as mock_discover, \
             patch("sagaz.cli.dry_run._interactive_saga_selection") as mock_interactive, \
             patch("sagaz.cli.dry_run._run_simulation_for_sagas") as mock_run, \
             patch("sagaz.cli.dry_run._display_simulation_results"):
            mock_discover.return_value = [{"name": "TestSaga0", "class": Mock}]
            mock_interactive.return_value = "TestSaga0"
            mock_run.return_value = [("TestSaga0", DryRunResult(mode=DryRunMode.SIMULATE, success=True))]
            result = runner.invoke(simulate_cmd, ["--interactive"], input="1\n")
        
        assert result.exit_code == 0

    def test_simulate_with_complex_context(self, temp_project_with_sagas, monkeypatch):
        """Test simulation with complex context."""
        monkeypatch.chdir(temp_project_with_sagas)
        runner = CliRunner()
        
        context = json.dumps({"nested": {"key": "value"}, "list": [1, 2, 3]})
        with patch("sagaz.cli.dry_run._discover_project_sagas") as mock_discover, \
             patch("sagaz.cli.dry_run._run_simulation_for_sagas") as mock_run, \
             patch("sagaz.cli.dry_run._display_simulation_results"):
            mock_discover.return_value = [{"name": "TestSaga", "class": Mock}]
            mock_run.return_value = [("TestSaga", DryRunResult(mode=DryRunMode.SIMULATE, success=True))]
            result = runner.invoke(simulate_cmd, ["--context", context])
        
        assert result.exit_code == 0


class TestErrorHandling:
    """Tests for error handling paths."""

    def test_invalid_json_context_validate(self):
        """Test validate with invalid JSON context."""
        runner = CliRunner()
        
        with patch("sagaz.cli.dry_run._discover_project_sagas", return_value=[]):
            result = runner.invoke(validate_cmd, ["--context", "{invalid json"])
        
        assert result.exit_code != 0

    def test_invalid_json_context_simulate(self):
        """Test simulate with invalid JSON context."""
        runner = CliRunner()
        
        with patch("sagaz.cli.dry_run._discover_project_sagas", return_value=[]):
            result = runner.invoke(simulate_cmd, ["--context", "not valid json"])
        
        assert result.exit_code != 0

    def test_no_sagas_yaml_file(self, tmp_path, monkeypatch):
        """Test behavior when no sagaz.yaml exists."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        
        result = runner.invoke(validate_cmd)
        
        assert result.exit_code == 1
        assert "No sagas found" in result.output


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_saga_paths(self, tmp_path, monkeypatch):
        """Test with empty paths in config."""
        monkeypatch.chdir(tmp_path)
        config = {
            "version": "1.0",
            "project": {"name": "test"},
            "paths": [],
        }
        (tmp_path / "sagaz.yaml").write_text(yaml.dump(config))
        
        runner = CliRunner()
        result = runner.invoke(validate_cmd)
        
        assert result.exit_code == 1

    def test_saga_with_no_steps(self, tmp_path, monkeypatch):
        """Test saga with no action methods."""
        monkeypatch.chdir(tmp_path)
        
        config = {"version": "1.0", "project": {"name": "test"}, "paths": ["sagas/"]}
        (tmp_path / "sagaz.yaml").write_text(yaml.dump(config))
        
        sagas_dir = tmp_path / "sagas"
        sagas_dir.mkdir()
        
        empty_saga = '''from sagaz import Saga
class EmptySaga(Saga):
    pass
'''
        (sagas_dir / "empty.py").write_text(empty_saga)
        
        runner = CliRunner()
        result = runner.invoke(validate_cmd)
        
        # Should handle gracefully
        assert result.exit_code in [0, 1]

    def test_multiple_validation_failures(self, tmp_path, monkeypatch):
        """Test handling multiple saga validation failures."""
        monkeypatch.chdir(tmp_path)
        
        mock_result_fail = DryRunResult(
            mode=DryRunMode.VALIDATE,
            success=False,
            validation_errors=["Critical error"]
        )
        
        from sagaz import Saga
        
        class MockSaga(Saga):
            pass
        
        sagas = [
            {"name": "FailSaga1", "class": MockSaga},
            {"name": "FailSaga2", "class": MockSaga},
        ]
        
        with patch("sagaz.cli.dry_run._discover_project_sagas", return_value=sagas), \
             patch("sagaz.cli.dry_run._run_validation_for_sagas") as mock_run, \
             patch("sagaz.cli.dry_run._display_validation_results"):
            mock_run.return_value = [
                ("FailSaga1", mock_result_fail),
                ("FailSaga2", mock_result_fail)
            ]
            
            runner = CliRunner()
            result = runner.invoke(validate_cmd)
            
            assert result.exit_code == 1
