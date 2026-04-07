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


class TestProjectMissingCoverage:
    """Cover cli/project.py missing lines: 13-14, 104, 113->116, 121-122, 192-193."""

    def test_list_sagas_without_sagaz_yaml(self, runner, tmp_path):
        """Lines 192-193: list_sagas exits when sagaz.yaml not found."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(list_sagas)
            assert result.exit_code != 0 or "sagaz.yaml not found" in result.output

    def test_console_is_none_without_rich(self):
        """Lines 13-14: when rich is not importable, console=None."""
        import sys
        import importlib
        import sagaz.cli.project as proj_mod

        original_rich = sys.modules.get("rich.console")
        try:
            sys.modules["rich.console"] = None  # type: ignore[assignment]
            importlib.reload(proj_mod)
            assert proj_mod.console is None
        finally:
            if original_rich is not None:
                sys.modules["rich.console"] = original_rich
            else:
                sys.modules.pop("rich.console", None)
            importlib.reload(proj_mod)

    def test_discover_sagas_from_file_bad_spec(self, tmp_path):
        """Line 104: returns [] when spec_from_file_location returns None."""
        from sagaz.cli.project import _inspect_module
        from unittest.mock import patch

        with patch("importlib.util.spec_from_file_location", return_value=None):
            result = _inspect_module("fake_mod", tmp_path / "fake.py")
        assert result == []

    def test_discover_sagas_from_file_exception(self, tmp_path):
        """Lines 121-122: exception during exec_module is caught silently."""
        from sagaz.cli.project import _inspect_module

        bad_py = tmp_path / "bad.py"
        bad_py.write_text("raise RuntimeError('intentional')\n")
        result = _inspect_module("bad_mod", bad_py)
        assert result == []

    def test_discover_sagas_from_file_default_docstring(self, tmp_path):
        """Lines 113->116: doc set to 'No description' when it matches Saga base docstring."""
        from sagaz.cli.project import _inspect_module
        from sagaz import Saga
        import inspect

        base_doc = inspect.getdoc(Saga) or ""
        saga_py = tmp_path / "saga_with_base_doc.py"
        saga_py.write_text(
            f'from sagaz import Saga\n'
            f'class MySaga(Saga):\n'
            f'    """{base_doc}"""\n'
            f'    pass\n'
        )
        results = _inspect_module("saga_with_base_doc", saga_py)
        assert any(r["doc"] == "No description" for r in results)


class TestCliProjectBranches:
    def test_inspect_module_custom_docstring_not_base(self, tmp_path):
        """113->116: doc != Saga base docstring → first_line used unchanged."""
        from sagaz.cli.project import _inspect_module

        saga_py = tmp_path / "custom.py"
        saga_py.write_text(
            "from sagaz import Saga\n"
            "class MySaga(Saga):\n"
            "    '''My completely unique custom description 1234.'''\n"
            "    pass\n"
        )
        results = _inspect_module("custom", saga_py)
        assert any("My completely unique custom description 1234" in r["doc"] for r in results)

    def test_iter_python_files_skips_dunder(self, tmp_path):
        """134->133: file starting with '__' is skipped."""
        from sagaz.cli.project import _iter_python_files

        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "saga.py").write_text("")
        results = list(_iter_python_files([str(tmp_path)]))
        names = [r.name for r in results]
        assert "saga.py" in names
        assert "__init__.py" not in names


# ==========================================================================
# cli/replay.py  – 252, 360, 416->exit
