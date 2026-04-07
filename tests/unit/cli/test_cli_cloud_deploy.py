"""
Unit tests for PR #65 — CLI v2.0 multi-cloud deployment commands:
  - sagaz deploy --provider aws|gcp|k8s
  - sagaz teardown --provider aws|gcp|k8s
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sagaz.cli.app import deploy_cmd, teardown_cmd

# ---------------------------------------------------------------------------
# deploy command
# ---------------------------------------------------------------------------


class TestDeployCommand:
    def test_cost_estimate_aws(self):
        runner = CliRunner()
        result = runner.invoke(deploy_cmd, ["--provider", "aws", "--cost-estimate"])
        assert result.exit_code == 0
        assert "aws" in result.output.lower()
        assert "ECS" in result.output

    def test_cost_estimate_gcp(self):
        runner = CliRunner()
        result = runner.invoke(deploy_cmd, ["--provider", "gcp", "--cost-estimate"])
        assert result.exit_code == 0
        assert "Cloud Run" in result.output

    def test_cost_estimate_k8s(self):
        runner = CliRunner()
        result = runner.invoke(deploy_cmd, ["--provider", "k8s", "--cost-estimate"])
        assert result.exit_code == 0
        assert "cluster" in result.output.lower() or "k8s" in result.output.lower()

    def test_deploy_aws_dry_run(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(deploy_cmd, ["--provider", "aws", "--dry-run"])
        assert result.exit_code == 0
        assert (
            "dry-run" in result.output.lower()
            or "dry_run" in result.output.lower()
            or "Would run" in result.output
        )

    def test_deploy_gcp_dry_run(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(deploy_cmd, ["--provider", "gcp", "--dry-run"])
        assert result.exit_code == 0

    def test_deploy_k8s_dry_run(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(deploy_cmd, ["--provider", "k8s", "--dry-run"])
        assert result.exit_code == 0

    def test_deploy_k8s_custom_namespace(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(deploy_cmd, ["--provider", "k8s", "--namespace", "production"])
        assert result.exit_code == 0
        assert "production" in result.output

    def test_deploy_aws_success(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(deploy_cmd, ["--provider", "aws"])
        assert result.exit_code == 0
        assert "complete" in result.output.lower() or "deploy" in result.output.lower()

    def test_deploy_aws_failure_reported(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = runner.invoke(deploy_cmd, ["--provider", "aws"])
        # Exit code of the CLI is still 0 (we report error via message)
        assert "failed" in result.output.lower() or result.exit_code != 0

    def test_invalid_provider_rejected(self):
        runner = CliRunner()
        result = runner.invoke(deploy_cmd, ["--provider", "azure"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# teardown command
# ---------------------------------------------------------------------------


class TestTeardownCommand:
    def test_teardown_aborted_without_yes(self):
        runner = CliRunner()
        result = runner.invoke(teardown_cmd, ["--provider", "aws"], input="n\n")
        assert result.exit_code == 0
        assert "Aborted" in result.output

    def test_teardown_aws_with_yes(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(teardown_cmd, ["--provider", "aws", "--yes"])
        assert result.exit_code == 0
        assert "complete" in result.output.lower()

    def test_teardown_gcp_with_yes(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(teardown_cmd, ["--provider", "gcp", "--yes"])
        assert result.exit_code == 0

    def test_teardown_k8s_with_yes(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(teardown_cmd, ["--provider", "k8s", "--yes"])
        assert result.exit_code == 0

    def test_teardown_k8s_custom_namespace(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(
                teardown_cmd, ["--provider", "k8s", "--namespace", "staging", "--yes"]
            )
        assert result.exit_code == 0
        assert "staging" in result.output

    def test_teardown_failure_reported(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = runner.invoke(teardown_cmd, ["--provider", "gcp", "--yes"])
        assert "failed" in result.output.lower() or result.exit_code != 0

    def test_teardown_prompts_for_confirmation(self):
        runner = CliRunner()
        with patch("sagaz.cli.app.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(teardown_cmd, ["--provider", "aws"], input="y\n")
        assert result.exit_code == 0
        assert "complete" in result.output.lower()

    def test_invalid_provider_rejected(self):
        runner = CliRunner()
        result = runner.invoke(teardown_cmd, ["--provider", "oracle"])
        assert result.exit_code != 0
