import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sagaz.cli.project import project_cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def temp_project_dir(tmp_path):
    d = tmp_path / "test_proj"
    d.mkdir()
    return d


def test_init_creates_scaffold(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(project_cli, ["init", "my_saga_project"])
        assert result.exit_code == 0
        assert "Initializing Sagaz project in my_saga_project/" in result.output

        project_path = Path("my_saga_project")
        assert project_path.exists()
        assert (project_path / "sagaz.yaml").exists()
        assert (project_path / "profiles.yaml").exists()
        assert (project_path / "sagas" / "example.py").exists()
        assert (project_path / ".gitignore").exists()


def test_init_fails_if_dir_exists_and_not_empty(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Create non-empty dir
        d = Path("existing_proj")
        d.mkdir()
        (d / "somefile.txt").touch()

        # input="n" to decline overwrite/continue
        result = runner.invoke(project_cli, ["init", "existing_proj"], input="n")
        assert result.exit_code == 0
        assert "Directory 'existing_proj' is not empty" in result.output
        assert not (d / "sagaz.yaml").exists()


def test_check_fails_without_sagaz_yaml(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(project_cli, ["check"])
        assert result.exit_code == 1
        assert "sagaz.yaml not found" in result.output


def test_check_validates_project(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Init first
        runner.invoke(project_cli, ["init", "my_proj"])
        os.chdir("my_proj")

        # Check
        result = runner.invoke(project_cli, ["check"])
        assert result.exit_code == 0
        assert "Checking project my_proj" in result.output
        assert "Check complete!" in result.output
        # Should find ExampleSaga
        assert "Found Saga: ExampleSaga" in result.output


def test_list_sagas(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(project_cli, ["init", "my_proj"])
        os.chdir("my_proj")

        result = runner.invoke(project_cli, ["list"])
        assert result.exit_code == 0
        assert "ExampleSaga" in result.output
        assert "sagas/example.py" in result.output


def test_check_warns_missing_paths(runner, tmp_path):
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(project_cli, ["init", "my_proj"])
        os.chdir("my_proj")

        # Modify sagaz.yaml to point to non-existent path
        config_file = Path("sagaz.yaml")
        content = config_file.read_text()
        config_file.write_text(content.replace("sagas/", "missing_sagas/"))

        result = runner.invoke(project_cli, ["check"])
        assert result.exit_code == 0
        assert "project my_proj" in result.output
        assert "Path 'missing_sagas/' does not exist" in result.output
