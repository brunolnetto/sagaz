"""``sagaz deploy`` / ``sagaz teardown`` with Terraform and Helm mocked (#49)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

from sagaz.cli import _deploy_runner, deploy
from sagaz.cli._deploy_cost import estimate, render, tf_defaults
from sagaz.cli.app import cli

VARIABLES_TF = """
variable "name" {
  type    = string
  default = "sagaz"
}
variable "image" {
  type = string
}
variable "db_instance_class" {
  default = "db.t4g.micro"
}
variable "worker_count" {
  default = 1
}
variable "db_multi_az" {
  default = false
}
variable "tags" {
  default = {}
}
"""

COST = {
    "provider": "aws",
    "currency": "USD",
    "region": "us-east-1",
    "priced_at": "2026-11",
    "items": [
        {
            "label": "RDS instance",
            "variable": "db_instance_class",
            "multiplier_variable": "db_multi_az",
            "prices": {"db.t4g.micro": 11.68, "db.t4g.small": 23.36},
        },
        {"label": "Fargate task", "quantity_variable": "worker_count", "prices": {"*": 9.0}},
    ],
    "fixed": [{"label": "Logs", "monthly": 0.5}],
    "notes": ["730 h/month"],
}


@pytest.fixture
def resources(tmp_path, monkeypatch):
    root = tmp_path / "resources"
    for provider in ("aws", "gcp"):
        module = root / "infra" / provider
        (module / "examples").mkdir(parents=True)
        (module / "main.tf").write_text("# module\n")
        (module / "variables.tf").write_text(VARIABLES_TF)
        (module / "cost.json").write_text(json.dumps({**COST, "provider": provider}))
        (module / "examples" / "minimal.tfvars").write_text('image = "x"\n')
    chart = root / "charts" / "sagaz"
    chart.mkdir(parents=True)
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: sagaz\nversion: 0.1.0\n")
    monkeypatch.setattr(_deploy_runner, "_resources", lambda: root)
    return root


@pytest.fixture
def calls(monkeypatch):
    """Record every tool invocation; ``terraform output -json`` returns outputs."""
    recorded: list[list[str]] = []
    outputs = {
        "worker_service_name": {"value": "sagaz-worker", "sensitive": False},
        "database_url": {"value": "postgresql://secret", "sensitive": True},
    }

    def fake_run(command, cwd=None, check=False, capture_output=False, text=False):
        recorded.append([Path(command[0]).name, *command[1:]])
        if command[1:3] == ["output", "-json"]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(outputs))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(_deploy_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(_deploy_runner.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    return recorded


def _sagaz(*args, input=None):
    return CliRunner().invoke(cli, list(args), input=input)


class TestTerraformDeploy:
    def test_deploy_runs_init_plan_apply_and_records_variables(self, resources, calls, tmp_path):
        state = tmp_path / "state"
        result = _sagaz(
            "deploy", "--provider", "aws", "--image", "ghcr.io/acme/sagaz:1.9.0",
            "--region", "eu-west-1", "--var", "worker_count=2", "--var", "db_multi_az=true",
            "--state-dir", str(state), "--yes",
        )  # fmt: skip

        assert result.exit_code == 0, result.output
        assert [c[1] for c in calls] == ["init", "plan", "apply", "output"]
        assert calls[1][-1] == "-out=sagaz.tfplan"
        assert calls[2][-1] == "sagaz.tfplan"
        assert json.loads((state / "sagaz.auto.tfvars.json").read_text()) == {
            "name": "sagaz",
            "image": "ghcr.io/acme/sagaz:1.9.0",
            "region": "eu-west-1",
            "worker_count": 2,
            "db_multi_az": True,
        }
        assert (state / "main.tf").is_file()
        assert (state / "examples" / "minimal.tfvars").is_file()
        assert "worker_service_name: sagaz-worker" in result.output
        assert "postgresql://secret" not in result.output

    def test_dry_run_stops_after_the_plan(self, resources, calls, tmp_path):
        result = _sagaz(
            "deploy", "--provider", "aws", "--image", "img:1", "--state-dir", str(tmp_path / "s"),
            "--dry-run",
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        assert [c[1] for c in calls] == ["init", "plan"]
        assert "Dry run: nothing was changed" in result.output

    def test_declining_the_confirmation_applies_nothing(self, resources, calls, tmp_path):
        result = _sagaz(
            "deploy", "--provider", "aws", "--image", "img:1", "--state-dir", str(tmp_path / "s"),
            input="n\n",
        )  # fmt: skip
        assert result.exit_code == 1
        assert "apply" not in [c[1] for c in calls]

    def test_cost_estimate_uses_defaults_and_overrides(self, resources, calls, tmp_path):
        result = _sagaz(
            "deploy", "--provider", "aws", "--image", "img:1", "--var", "worker_count=3",
            "--state-dir", str(tmp_path / "s"), "--cost-estimate", "--dry-run",
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        assert "RDS instance (db.t4g.micro)" in result.output
        assert "27.00" in result.output  # 3 Fargate tasks x 9.00
        assert "Total" in result.output
        assert "39.18" in result.output  # 11.68 + 27.00 + 0.50

    def test_gcp_needs_a_project(self, resources, calls, tmp_path):
        result = _sagaz("deploy", "--provider", "gcp", "--image", "img:1")
        assert result.exit_code == 2
        assert "--project-id is required" in result.output
        ok = _sagaz(
            "deploy", "--provider", "gcp", "--image", "img:1", "--project-id", "acme",
            "--state-dir", str(tmp_path / "g"), "--dry-run",
        )  # fmt: skip
        assert ok.exit_code == 0, ok.output
        assert (
            json.loads((tmp_path / "g" / "sagaz.auto.tfvars.json").read_text())["project_id"]
            == "acme"
        )

    def test_cloud_deploys_need_an_image(self, resources, calls):
        result = _sagaz("deploy", "--provider", "aws")
        assert result.exit_code == 2
        assert "--image is required" in result.output
        assert calls == []

    def test_image_can_come_from_a_var(self, resources, calls, tmp_path):
        result = _sagaz(
            "deploy", "--provider", "aws", "--var", "image=img:2",
            "--state-dir", str(tmp_path / "s"), "--dry-run",
        )  # fmt: skip
        assert result.exit_code == 0, result.output

    def test_missing_terraform_is_explained(self, resources, monkeypatch, tmp_path):
        monkeypatch.setattr(_deploy_runner.shutil, "which", lambda tool: None)
        result = _sagaz("deploy", "--provider", "aws", "--image", "i", "--state-dir", str(tmp_path))
        assert result.exit_code == 1
        assert "'terraform' is required" in result.output
        assert "developer.hashicorp.com" in result.output

    def test_a_failing_tool_stops_the_deploy(self, resources, monkeypatch, tmp_path):
        monkeypatch.setattr(_deploy_runner.shutil, "which", lambda tool: f"/bin/{tool}")
        monkeypatch.setattr(
            _deploy_runner.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=3, stdout=""),
        )
        result = _sagaz("deploy", "--provider", "aws", "--image", "i", "--state-dir", str(tmp_path))
        assert result.exit_code == 1
        assert "terraform exited with status 3" in result.output

    def test_missing_module_is_reported(self, resources, calls, tmp_path):
        (resources / "infra" / "aws" / "main.tf").unlink()
        result = _sagaz("deploy", "--provider", "aws", "--image", "i", "--state-dir", str(tmp_path))
        assert result.exit_code == 1
        assert "No Terraform module for 'aws'" in result.output


class TestTerraformTeardown:
    def _deployed(self, tmp_path, calls):
        state = tmp_path / "state"
        _sagaz(
            "deploy", "--provider", "aws", "--image", "i", "--name", "shop",
            "--state-dir", str(state), "--yes",
        )  # fmt: skip
        calls.clear()
        return state

    def test_teardown_needs_the_name_typed(self, resources, calls, tmp_path):
        state = self._deployed(tmp_path, calls)

        wrong = _sagaz("teardown", "--provider", "aws", "--state-dir", str(state), input="nope\n")
        assert wrong.exit_code == 1
        assert calls == []

        right = _sagaz("teardown", "--provider", "aws", "--state-dir", str(state), input="shop\n")
        assert right.exit_code == 0, right.output
        assert [c[1] for c in calls] == ["init", "destroy"]
        assert "-auto-approve" in calls[1]
        assert "Destroyed the 'shop' stack on aws" in right.output

    def test_teardown_with_yes(self, resources, calls, tmp_path):
        state = self._deployed(tmp_path, calls)
        result = _sagaz("teardown", "--provider", "aws", "--state-dir", str(state), "--yes")
        assert result.exit_code == 0, result.output

    def test_nothing_to_tear_down(self, resources, calls, tmp_path):
        result = _sagaz("teardown", "--provider", "aws", "--state-dir", str(tmp_path / "x"))
        assert result.exit_code == 1
        assert "No sagaz deployment found" in result.output


class TestKubernetes:
    def test_dry_run_renders_with_image_and_values(self, resources, calls, tmp_path):
        values = tmp_path / "values.yaml"
        values.write_text("replicaCount: 2\n")
        result = _sagaz(
            "deploy", "--provider", "k8s", "--namespace", "prod",
            "--image", "registry.local:5000/sagaz/worker:1.9.0", "--values", str(values),
            "--var", "broker.type=redis", "--dry-run", "--cost-estimate",
        )  # fmt: skip

        assert result.exit_code == 0, result.output
        (command,) = calls
        assert command[:3] == ["helm", "template", "sagaz"]
        assert command[command.index("--namespace") + 1] == "prod"
        assert ["-f", str(values)] == command[command.index("-f") : command.index("-f") + 2]
        sets = [command[i + 1] for i, arg in enumerate(command) if arg == "--set"]
        assert sets == [
            "image.repository=registry.local:5000/sagaz/worker",
            "image.tag=1.9.0",
            "broker.type=redis",
        ]
        assert "no estimate is made" in result.output

    def test_install_and_uninstall(self, resources, calls):
        installed = _sagaz("deploy", "--provider", "k8s", "--yes")
        assert installed.exit_code == 0, installed.output
        assert calls[0][:4] == ["helm", "upgrade", "--install", "sagaz"]
        assert "--create-namespace" in calls[0]

        declined = _sagaz("teardown", "--provider", "k8s", input="n\n")
        assert declined.exit_code == 1
        removed = _sagaz("teardown", "--provider", "k8s", "--name", "sagaz", "--yes")
        assert removed.exit_code == 0, removed.output
        assert calls[-1] == ["helm", "uninstall", "sagaz", "--namespace", "sagaz"]

    def test_install_asks_first(self, resources, calls):
        result = _sagaz("deploy", "--provider", "k8s", input="n\n")
        assert result.exit_code == 1
        assert calls == []

    def test_missing_chart_is_reported(self, resources, calls):
        (resources / "charts" / "sagaz" / "Chart.yaml").unlink()
        result = _sagaz("deploy", "--provider", "k8s", "--dry-run")
        assert result.exit_code == 1
        assert "Helm chart is not available" in result.output


class TestHelpers:
    @pytest.mark.parametrize(
        ("image", "expected"),
        [
            ("ghcr.io/acme/sagaz:1.9.0", ("ghcr.io/acme/sagaz", "1.9.0")),
            ("registry:5000/sagaz", ("registry:5000/sagaz", None)),
            ("sagaz", ("sagaz", None)),
        ],
    )
    def test_split_image(self, image, expected):
        assert deploy.split_image(image) == expected

    def test_parse_vars(self):
        assert deploy.parse_vars(("a=1", "b=true", "c=text", "d=")) == {
            "a": 1,
            "b": True,
            "c": "text",
            "d": "",
        }
        with pytest.raises(click.BadParameter):
            deploy.parse_vars(("novalue",))

    def test_terraform_outputs_without_state(self, resources, monkeypatch, tmp_path):
        monkeypatch.setattr(_deploy_runner.shutil, "which", lambda tool: "/bin/terraform")
        monkeypatch.setattr(
            _deploy_runner.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=1, stdout=""),
        )
        assert _deploy_runner.TerraformStack("aws", tmp_path).outputs() == {}


class TestCostEstimate:
    def test_defaults_are_read_from_variables_tf(self):
        assert tf_defaults(VARIABLES_TF) == {
            "name": "sagaz",
            "db_instance_class": "db.t4g.micro",
            "worker_count": 1,
            "db_multi_az": False,
        }

    def test_ha_doubles_and_unpriced_sizes_are_flagged(self):
        values = {**tf_defaults(VARIABLES_TF), "db_multi_az": True}
        assert estimate(COST, values).total == round(11.68 * 2 + 9.0 + 0.5, 2)

        unpriced = estimate(COST, {**values, "db_instance_class": "db.r7g.24xlarge"})
        assert not unpriced.complete
        text = render(unpriced)
        assert "not priced" in text
        assert "the total excludes them" in text

    def test_memory_units_and_per_unit_divisor(self):
        cost = {
            "items": [
                {
                    "label": "Memory",
                    "per_unit_variable": "worker_memory",
                    "per_unit_unit": "GiB",
                    "prices": {"*": 4.0},
                },
                {
                    "label": "vCPU",
                    "per_unit_variable": "worker_cpu",
                    "per_unit_divisor": 1024,
                    "prices": {"*": 30.0},
                },
            ]
        }
        result = estimate(cost, {"worker_memory": "512Mi", "worker_cpu": 512})
        assert [line.monthly for line in result.lines] == [2.0, 15.0]
        with pytest.raises(ValueError, match="not a number"):
            estimate(cost, {"worker_memory": "lots", "worker_cpu": 1})


def test_cost_edge_values():
    from sagaz.cli._deploy_cost import _number

    assert tf_defaults('variable "tier" {\n  default = BASIC\n}\n') == {"tier": "BASIC"}
    assert _number(True) == 1.0
    assert _number("2Gi", "GiB") == 2.0
    assert _number("1.5") == 1.5


def test_multipliers_by_value():
    cost = {
        "items": [
            {
                "label": "Cloud SQL",
                "variable": "db_tier",
                "multiplier_variable": "db_availability_type",
                "multipliers": {"ZONAL": 1, "REGIONAL": 2},
                "prices": {"db-f1-micro": 7.67},
            }
        ]
    }
    zonal = estimate(cost, {"db_tier": "db-f1-micro", "db_availability_type": "ZONAL"})
    regional = estimate(cost, {"db_tier": "db-f1-micro", "db_availability_type": "REGIONAL"})
    other = estimate(cost, {"db_tier": "db-f1-micro", "db_availability_type": "MULTI"})
    assert [zonal.total, regional.total, other.total] == [7.67, 15.34, 7.67]
