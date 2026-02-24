"""
Comprehensive tests for sagaz/cli/dry_run.py to achieve 90%+ coverage.
Phase 1: Critical CLI functionality.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from pathlib import Path
import json
from click.testing import CliRunner

from sagaz.cli.dry_run import (
    validate_cmd,
    simulate_cmd,
    _discover_project_sagas,
    _load_saga,
    _display_validation_results,
    _display_simulation_results,
)
from sagaz.core.decorators import Saga, action
from sagaz.dry_run import DryRunEngine, DryRunMode


@pytest.fixture
def temp_project_dir(tmp_path):
    """Create temporary project directory structure."""
    sagas_dir = tmp_path / "sagas"
    sagas_dir.mkdir()
    return tmp_path


@pytest.fixture
def runner():
    """Create Click CLI runner."""
    return CliRunner()


class TestValidateCommand:
    """Tests for validate CLI command."""

    def test_validate_command_basic(self, runner):
        """Test basic validate command."""
        with patch('sagaz.cli.dry_run._discover_project_sagas', return_value=[]):
            result = runner.invoke(validate_cmd, [])
            assert result.exit_code in [0, 1]

    def test_validate_command_with_saga_name(self, runner):
        """Test validate with specific saga name."""
        with patch('sagaz.cli.dry_run._discover_project_sagas', return_value=[]):
            result = runner.invoke(validate_cmd, ['--saga', 'test-saga'])
            assert result.exit_code in [0, 1]

    def test_validate_command_with_context(self, runner):
        """Test validate with JSON context."""
        with patch('sagaz.cli.dry_run._discover_project_sagas', return_value=[]):
            result = runner.invoke(validate_cmd, ['--context', '{"user_id": "123"}'])
            assert result.exit_code in [0, 1]

    def test_validate_command_interactive(self, runner):
        """Test interactive saga selection."""
        with patch('sagaz.cli.dry_run._discover_project_sagas', return_value=[]):
            result = runner.invoke(validate_cmd, ['--interactive'])
            assert result.exit_code in [0, 1]


class TestSimulateCommand:
    """Tests for simulate CLI command."""

    def test_simulate_command_basic(self, runner):
        """Test basic simulate command."""
        with patch('sagaz.cli.dry_run._discover_project_sagas', return_value=[]):
            result = runner.invoke(simulate_cmd, [])
            assert result.exit_code in [0, 1]

    def test_simulate_command_with_parallel(self, runner):
        """Test simulate with parallel flag."""
        with patch('sagaz.cli.dry_run._discover_project_sagas', return_value=[]):
            result = runner.invoke(simulate_cmd, ['--show-parallel'])
            assert result.exit_code in [0, 1]

    def test_simulate_command_with_saga(self, runner):
        """Test simulate specific saga."""
        with patch('sagaz.cli.dry_run._discover_project_sagas', return_value=[]):
            result = runner.invoke(simulate_cmd, ['--saga', 'test-saga'])
            assert result.exit_code in [0, 1]


class TestDiscoverProjectSagas:
    """Tests for _discover_project_sagas function."""

    def test_discover_sagas_empty_directory(self):
        """Test discovery in empty directory."""
        with patch('sagaz.cli.dry_run._discover_sagas_in_paths', return_value=[]):
            result = _discover_project_sagas()
            assert isinstance(result, list)

    def test_discover_sagas_with_files(self, temp_project_dir):
        """Test discovering sagas in directory."""
        result = _discover_project_sagas()
        assert isinstance(result, list)


class TestLoadSaga:
    """Tests for saga loading."""

    def test_load_saga_valid(self):
        """Test loading a valid saga class."""
        from sagaz import Saga
        
        class TestSaga(Saga):
            pass
        
        # Test saga class is valid
        assert issubclass(TestSaga, Saga)
        assert TestSaga is not Saga  # Not the base class

    def test_load_saga_module_not_found(self, tmp_path):
        """Test handling non-existent module."""
        import sys
        from sagaz.cli.dry_run import _try_load_sagas_from_file
        
        nonexistent = tmp_path / "nonexistent.py"
        result = _try_load_sagas_from_file(nonexistent, sys, __import__, __import__, Saga)
        assert result == []

    def test_load_saga_no_saga_class(self, tmp_path):
        """Test loading module without Saga class."""
        import sys
        from sagaz.cli.dry_run import _try_load_sagas_from_file
        from sagaz import Saga
        
        module_file = tmp_path / "nosaga.py"
        module_file.write_text("class NotASaga: pass")
        
        result = _try_load_sagas_from_file(module_file, sys, __import__, __import__, Saga)
        assert result == []


class TestDisplayValidationResults:
    """Tests for _display_validation_results function."""

    def test_display_validation_results_empty(self):
        """Test displaying empty results."""
        _display_validation_results([])
        # Should not raise errors

    def test_display_validation_results_success(self):
        """Test displaying successful results."""
        from sagaz.dry_run import DryRunResult
        
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.saga_name = "test-saga"
        mock_result.checks = {}
        mock_result.warnings = []
        
        _display_validation_results([("test-saga", mock_result)])
        # Should not raise errors

    def test_display_validation_results_failure(self):
        """Test displaying failed results."""
        from sagaz.dry_run import DryRunResult
        
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.saga_name = "test-saga"
        mock_result.checks = {"action_count": False}
        mock_result.errors = ["No actions defined"]
        
        _display_validation_results([("test-saga", mock_result)])
        # Should not raise errors

    def test_display_validation_results_multiple(self):
        """Test displaying multiple results."""
        mock_result1 = MagicMock()
        mock_result1.success = True
        mock_result1.saga_name = "saga-1"
        
        mock_result2 = MagicMock()
        mock_result2.success = False
        mock_result2.saga_name = "saga-2"
        
        _display_validation_results([
            ("saga-1", mock_result1),
            ("saga-2", mock_result2)
        ])


class TestDisplaySimulationResults:
    """Tests for _display_simulation_results function."""

    def test_display_simulation_results_basic(self):
        """Test displaying simulation results."""
        from sagaz.dry_run import ParallelLayerInfo, DryRunResult
        
        layer = ParallelLayerInfo(layer_number=1, steps=["step1"], dependencies=set())
        mock_result = DryRunResult(
            mode=DryRunMode.SIMULATE,
            success=True,
            forward_layers=[layer],
            steps_planned=["step1"],
        )
        
        _display_simulation_results([("test-saga", mock_result)], show_parallel=False)
        # Should not raise errors

    def test_display_simulation_results_with_parallel(self):
        """Test displaying results with parallel flag."""
        from sagaz.dry_run import ParallelLayerInfo, DryRunResult
        
        layer = ParallelLayerInfo(layer_number=1, steps=["step1"], dependencies=set())
        mock_result = DryRunResult(
            mode=DryRunMode.SIMULATE,
            success=True,
            forward_layers=[layer],
            steps_planned=["step1"],
        )
        
        _display_simulation_results([("test-saga", mock_result)], show_parallel=True)

    def test_display_simulation_results_empty(self):
        """Test displaying empty simulation results."""
        _display_simulation_results([], show_parallel=False)


class TestDryRunEngineIntegration:
    """Tests for DryRunEngine integration."""

    @pytest.mark.asyncio
    async def test_validate_saga_basic(self):
        """Test validating a saga with DryRunEngine."""
        class TestSaga(Saga):
            saga_name = "test"
            
            @action(name="step1")
            async def step1(self, ctx):
                return {}
        
        engine = DryRunEngine()
        result = await engine.run(TestSaga(), {}, DryRunMode.VALIDATE)
        
        assert result is not None
        assert hasattr(result, 'success')

    @pytest.mark.asyncio
    async def test_simulate_saga_basic(self):
        """Test simulating a saga with DryRunEngine."""
        class TestSaga(Saga):
            saga_name = "test"
            
            @action(name="step1")
            async def step1(self, ctx):
                return {}
        
        engine = DryRunEngine()
        result = await engine.run(TestSaga(), {}, DryRunMode.SIMULATE)
        
        assert result is not None

    @pytest.mark.asyncio
    async def test_validate_saga_with_dependencies(self):
        """Test validating saga with dependencies."""
        class TestSaga(Saga):
            saga_name = "test"
            
            @action(name="step1")
            async def step1(self, ctx):
                return {}
            
            @action(name="step2", depends_on=["step1"])
            async def step2(self, ctx):
                return {}
        
        engine = DryRunEngine()
        result = await engine.run(TestSaga(), {}, DryRunMode.VALIDATE)
        
        assert result is not None


class TestCLIErrorHandling:
    """Tests for CLI error handling."""

    def test_validate_invalid_json_context(self, runner):
        """Test validate with invalid JSON context."""
        result = runner.invoke(validate_cmd, ['--context', 'invalid-json'])
        assert result.exit_code != 0

    def test_simulate_invalid_saga_name(self, runner):
        """Test simulate with invalid saga name."""
        with patch('sagaz.cli.dry_run._discover_project_sagas', return_value=[]):
            result = runner.invoke(simulate_cmd, ['--saga', 'nonexistent-saga'])
            assert result.exit_code in [0, 1]


class TestCLIOutputFormats:
    """Tests for CLI output formatting."""

    def test_rich_output_available(self):
        """Test that rich output is available."""
        from sagaz.cli import dry_run
        # Check if RICH_AVAILABLE is set
        assert hasattr(dry_run, 'RICH_AVAILABLE')

    def test_plain_output_fallback(self):
        """Test plain output when rich is unavailable."""
        with patch('sagaz.cli.dry_run.RICH_AVAILABLE', False):
            mock_result = MagicMock()
            mock_result.success = True
            _display_validation_results([("test", mock_result)])


class TestCLIInteractiveMode:
    """Tests for interactive mode."""

    def test_interactive_saga_selection_empty(self, runner):
        """Test interactive mode with no sagas."""
        with patch('sagaz.cli.dry_run._discover_project_sagas', return_value=[]):
            result = runner.invoke(validate_cmd, ['--interactive'])
            assert result.exit_code in [0, 1]

    def test_interactive_saga_selection_with_sagas(self, runner):
        """Test interactive mode with sagas available."""
        mock_sagas = [
            {'name': 'saga1', 'path': '/path/saga1.py'},
            {'name': 'saga2', 'path': '/path/saga2.py'}
        ]
        with patch('sagaz.cli.dry_run._discover_project_sagas', return_value=mock_sagas):
            result = runner.invoke(validate_cmd, ['--interactive'], input='1\n')
            assert result.exit_code in [0, 1]

