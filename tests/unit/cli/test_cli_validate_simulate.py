"""
Tests for project-level validate and simulate CLI commands.

Tests cover:
- Project-level saga discovery
- Validation of all sagas in project
- Simulation of all sagas in project
- Filtering by specific saga name
- Context passing
- Error handling
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from sagaz.cli.dry_run import simulate_cmd, validate_cmd


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project with sagaz.yaml and sagas."""
    # Create sagaz.yaml
    config = {
        "version": "1.0",
        "project": {"name": "test-project", "environment": "test"},
        "paths": ["sagas/"],
    }
    (tmp_path / "sagaz.yaml").write_text(yaml.dump(config))
    
    # Create sagas directory
    sagas_dir = tmp_path / "sagas"
    sagas_dir.mkdir()
    
    # Create simple saga
    simple_saga = '''"""Simple test saga."""
from sagaz import Saga, action


class SimpleSaga(Saga):
    """Simple saga with two steps."""
    
    def __init__(self):
        super().__init__()
    
    @action("step1")
    def step1(self, ctx):
        return {"result": "done"}
    
    @action("step2", depends_on=["step1"])
    def step2(self, ctx):
        return {"result": "done"}
'''
    (sagas_dir / "simple_saga.py").write_text(simple_saga)
    
    # Create parallel saga
    parallel_saga = '''"""Parallel test saga."""
from sagaz import Saga, action


class ParallelSaga(Saga):
    """Saga with parallel steps."""
    
    def __init__(self):
        super().__init__()
    
    @action("init")
    def init_step(self, ctx):
        return {"initialized": True}
    
    @action("process_a", depends_on=["init"])
    def process_a(self, ctx):
        return {"a": "done"}
    
    @action("process_b", depends_on=["init"])
    def process_b(self, ctx):
        return {"b": "done"}
    
    @action("finalize", depends_on=["process_a", "process_b"])
    def finalize(self, ctx):
        return {"final": "complete"}
'''
    (sagas_dir / "parallel_saga.py").write_text(parallel_saga)
    
    return tmp_path


@pytest.fixture
def empty_project(tmp_path):
    """Create a project with no sagas."""
    config = {
        "version": "1.0",
        "project": {"name": "empty-project"},
        "paths": ["sagas/"],
    }
    (tmp_path / "sagaz.yaml").write_text(yaml.dump(config))
    (tmp_path / "sagas").mkdir()
    return tmp_path


class TestValidateCommand:
    """Tests for validate command."""
    
    def test_validate_all_sagas_success(self, temp_project):
        """Test validating all sagas in project."""
        runner = CliRunner()
        
        # Change to the temp project directory
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(validate_cmd, [])
            
            assert result.exit_code == 0, f"Output: {result.output}"
            assert "All sagas validated successfully" in result.output
            assert "SimpleSaga" in result.output
            assert "ParallelSaga" in result.output
        finally:
            os.chdir(original_cwd)
    
    def test_validate_specific_saga(self, temp_project):
        """Test validating a specific saga."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(validate_cmd, ["--saga", "SimpleSaga"])
            
            assert result.exit_code == 0
            assert "SimpleSaga" in result.output
            assert "ParallelSaga" not in result.output
        finally:
            os.chdir(original_cwd)
    
    def test_validate_nonexistent_saga(self, temp_project):
        """Test validating a saga that doesn't exist."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(validate_cmd, ["--saga", "NonexistentSaga"])
            
            assert result.exit_code == 1
            assert "not found" in result.output
        finally:
            os.chdir(original_cwd)
    
    def test_validate_with_context(self, temp_project):
        """Test validation with custom context."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            ctx = json.dumps({"test_key": "test_value"})
            result = runner.invoke(validate_cmd, ["--context", ctx])
            
            assert result.exit_code == 0
        finally:
            os.chdir(original_cwd)
    
    def test_validate_no_sagas(self, empty_project):
        """Test validation when no sagas found."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(empty_project)
            result = runner.invoke(validate_cmd, [])
            
            assert result.exit_code == 1
            assert "No sagas found" in result.output
        finally:
            os.chdir(original_cwd)
    
    def test_validate_no_sagaz_yaml(self):
        """Test validation without sagaz.yaml."""
        runner = CliRunner()
        
        with runner.isolated_filesystem():
            result = runner.invoke(validate_cmd, [])
            
            assert result.exit_code == 1
            assert "No sagas found" in result.output


class TestSimulateCommand:
    """Tests for simulate command."""
    
    def test_simulate_all_sagas_success(self, temp_project):
        """Test simulating all sagas in project."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(simulate_cmd, [])
            
            assert result.exit_code == 0
            assert "All sagas simulated successfully" in result.output
            assert "SimpleSaga" in result.output
            assert "ParallelSaga" in result.output
            assert "Forward Execution Layers" in result.output
            assert "Parallelization Analysis" in result.output
        finally:
            os.chdir(original_cwd)
    
    def test_simulate_specific_saga(self, temp_project):
        """Test simulating a specific saga."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(simulate_cmd, ["--saga", "ParallelSaga"])
            
            assert result.exit_code == 0
            assert "ParallelSaga" in result.output
            assert "SimpleSaga" not in result.output
            # Check for parallelization
            assert "Max parallel width" in result.output
        finally:
            os.chdir(original_cwd)
    
    def test_simulate_shows_parallel_layers(self, temp_project):
        """Test that simulation shows parallel execution layers."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(simulate_cmd, ["--saga", "ParallelSaga"])
            
            assert result.exit_code == 0
            # ParallelSaga should have steps that can run in parallel
            assert "Layer 0" in result.output
            assert "Layer 1" in result.output
            assert "Layer 2" in result.output
            # Check for parallel steps in Layer 1
            assert "process_a" in result.output
            assert "process_b" in result.output
        finally:
            os.chdir(original_cwd)
    
    def test_simulate_shows_critical_path(self, temp_project):
        """Test that simulation shows critical path."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(simulate_cmd, ["--saga", "ParallelSaga"])
            
            assert result.exit_code == 0
            assert "Critical Path" in result.output
        finally:
            os.chdir(original_cwd)
    
    def test_simulate_with_show_parallel_flag(self, temp_project):
        """Test simulation with --show-parallel flag."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(simulate_cmd, ["--show-parallel"])
            
            assert result.exit_code == 0
            # Should show legacy parallel groups if any
            assert "simulated successfully" in result.output
        finally:
            os.chdir(original_cwd)
    
    def test_simulate_nonexistent_saga(self, temp_project):
        """Test simulating a saga that doesn't exist."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            result = runner.invoke(simulate_cmd, ["--saga", "NonexistentSaga"])
            
            assert result.exit_code == 1
            assert "not found" in result.output
        finally:
            os.chdir(original_cwd)
    
    def test_simulate_with_context(self, temp_project):
        """Test simulation with custom context."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_project)
            ctx = json.dumps({"test_key": "test_value"})
            result = runner.invoke(simulate_cmd, ["--context", ctx])
            
            assert result.exit_code == 0
        finally:
            os.chdir(original_cwd)
    
    def test_simulate_no_sagas(self, empty_project):
        """Test simulation when no sagas found."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(empty_project)
            result = runner.invoke(simulate_cmd, [])
            
            assert result.exit_code == 1
            assert "No sagas found" in result.output
        finally:
            os.chdir(original_cwd)


class TestInvalidSaga:
    """Tests for handling invalid sagas."""
    
    @pytest.fixture
    def invalid_project(self, tmp_path):
        """Create a project with an invalid saga."""
        config = {
            "version": "1.0",
            "project": {"name": "invalid-project"},
            "paths": ["sagas/"],
        }
        (tmp_path / "sagaz.yaml").write_text(yaml.dump(config))
        
        sagas_dir = tmp_path / "sagas"
        sagas_dir.mkdir()
        
        # Create saga with circular dependency
        invalid_saga = '''"""Invalid saga with circular dependency."""
from sagaz import Saga, action


class InvalidSaga(Saga):
    """Saga with circular dependency."""
    
    def __init__(self):
        super().__init__()
    
    @action("step1", depends_on=["step2"])
    def step1(self, ctx):
        return {}
    
    @action("step2", depends_on=["step1"])
    def step2(self, ctx):
        return {}
'''
        (sagas_dir / "invalid_saga.py").write_text(invalid_saga)
        
        return tmp_path
    
    def test_validate_invalid_saga(self, invalid_project):
        """Test validating saga with circular dependencies."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(invalid_project)
            result = runner.invoke(validate_cmd, [])
            
            assert result.exit_code == 1
            # Either no sagas found (if parsing failed) or validation failed
            assert ("failed" in result.output.lower() or "no sagas" in result.output.lower())
        finally:
            os.chdir(original_cwd)


class TestSagaWithNoSteps:
    """Tests for sagas with no steps defined."""
    
    @pytest.fixture
    def empty_saga_project(self, tmp_path):
        """Create a project with a saga that has no steps."""
        config = {
            "version": "1.0",
            "project": {"name": "empty-saga-project"},
            "paths": ["sagas/"],
        }
        (tmp_path / "sagaz.yaml").write_text(yaml.dump(config))
        
        sagas_dir = tmp_path / "sagas"
        sagas_dir.mkdir()
        
        empty_saga = '''"""Saga with no steps."""
from sagaz import Saga


class EmptySaga(Saga):
    """Saga with no steps defined."""
    
    def __init__(self):
        super().__init__()
'''
        (sagas_dir / "empty_saga.py").write_text(empty_saga)
        
        return tmp_path
    
    def test_validate_saga_no_steps(self, empty_saga_project):
        """Test validating saga with no steps."""
        runner = CliRunner()
        
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(empty_saga_project)
            result = runner.invoke(validate_cmd, [])
            
            assert result.exit_code == 1
            # Either no sagas found (if not recognized) or validation shows no steps
            assert ("no steps" in result.output.lower() or "no sagas" in result.output.lower())
        finally:
            os.chdir(original_cwd)
