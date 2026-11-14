"""`sagaz init --local` (issue #48).

Template copying and packaging are covered in test_deployment_templates.py.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import click
import pytest
import yaml
from click.testing import CliRunner

from sagaz.cli import _init_handlers as handlers
from sagaz.cli.app import cli

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "sagaz"


class TestInitLocal:
    # Project name, location, example choice, then the local setup questions
    # (storage, broker, outbox, metrics, tracing, logging, benchmarks, dev mode).
    ANSWERS = "shop\n\n\n\n\n\n\n\n\n\n\n\n"

    def test_creates_project_and_compose_side_by_side(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
            result = runner.invoke(cli, ["init", "--local"], input=self.ANSWERS)
            project = Path(cwd) / "shop"

            assert result.exit_code == 0, result.output
            assert (project / "sagaz.yaml").exists()
            assert (project / "docker-compose.yaml").exists()
            assert not (Path(cwd) / "docker-compose.yaml").exists()
            assert "Mode: local" in result.output
            assert "Start it with: cd shop && sagaz dev" in result.output

    def test_without_local_no_compose_is_written(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as cwd:
            result = runner.invoke(cli, ["init"], input="shop\n\n\n")

            assert result.exit_code == 0, result.output
            assert (Path(cwd) / "shop" / "sagaz.yaml").exists()
            assert not (Path(cwd) / "shop" / "docker-compose.yaml").exists()

    def test_help_documents_the_flag(self):
        result = CliRunner().invoke(cli, ["init", "--help"])
        assert "--local" in result.output
        assert "sagaz init --local" in result.output
