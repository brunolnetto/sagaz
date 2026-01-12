import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sagaz.cli.project import check, list_sagas


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def temp_project_dir(tmp_path):
    d = tmp_path / "test_proj"
    d.mkdir()
    return d


@pytest.fixture
def sample_project(tmp_path):
    """Create a sample project structure for testing."""
    project_dir = tmp_path / "my_saga_project"
    project_dir.mkdir()

    # Create directories
    (project_dir / "sagas").mkdir()
    (project_dir / "tests").mkdir()
    (project_dir / ".sagaz").mkdir()

    # Create sagaz.yaml
    sagaz_yaml = """name: my_saga_project
version: "0.1.0"
profile: default

paths:
  - sagas/

config:
  default_timeout: 60
  failure_strategy: FAIL_FAST_WITH_GRACE
"""
    (project_dir / "sagaz.yaml").write_text(sagaz_yaml)

    # Create example saga
    example_saga = """from sagaz import Saga, action, SagaContext

class ExampleSaga(Saga):
    def __init__(self):
        super().__init__()

    @action("step_one")
    def step_one(self, ctx: SagaContext):
        print("Executing step one")
        return {"result": "success"}
"""
    (project_dir / "sagas" / "example.py").write_text(example_saga)

    return project_dir


def test_check_fails_without_sagaz_yaml(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(check)
        assert result.exit_code == 1
        assert "sagaz.yaml not found" in result.output


def test_check_validates_project(runner, sample_project):
    with runner.isolated_filesystem():
        os.chdir(sample_project)

        # Check
        result = runner.invoke(check)
        assert result.exit_code == 0
        assert "Checking project" in result.output or "my_saga_project" in result.output
        assert "Check complete!" in result.output
        # Should find ExampleSaga
        assert "Found Saga: ExampleSaga" in result.output or "ExampleSaga" in result.output


def test_list_sagas(runner, sample_project):
    with runner.isolated_filesystem():
        os.chdir(sample_project)

        result = runner.invoke(list_sagas)
        assert result.exit_code == 0
        assert "ExampleSaga" in result.output
        assert "sagas/example.py" in result.output or "example.py" in result.output


def test_check_warns_missing_paths(runner, sample_project):
    with runner.isolated_filesystem():
        os.chdir(sample_project)

        # Modify sagaz.yaml to point to non-existent path
        config_file = Path("sagaz.yaml")
        content = config_file.read_text()
        config_file.write_text(content.replace("sagas/", "missing_sagas/"))

        result = runner.invoke(check)
        assert result.exit_code == 0
        assert "project" in result.output or "my_saga_project" in result.output
        assert "Path 'missing_sagas/' does not exist" in result.output
