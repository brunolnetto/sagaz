"""Static checks of the GCP Terraform module used by ``sagaz deploy --provider gcp``.

No network or terraform binary is needed, except for the ``terraform validate`` /
``terraform test`` check, which runs only when terraform is installed and
``SAGAZ_OFFLINE`` is not set (``terraform init`` downloads the providers).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import sagaz
from tests.unit.deployment._terraform_pins import pinned_major

PACKAGE_ROOT = Path(sagaz.__file__).parent
RESOURCES = PACKAGE_ROOT / "deployment" / "resources"
MODULE = RESOURCES / "infra" / "gcp"
REPO_ROOT = PACKAGE_ROOT.parent

CONTRACT_VARIABLES = {
    "name": "sagaz",
    "environment": "prod",
    "region": "us-central1",
    "labels": None,
    "project_id": None,
    "image": None,
    "worker_count": 1,
    "worker_cpu": "1",
    "worker_memory": "512Mi",
    "db_tier": "db-f1-micro",
    "db_storage_gb": 10,
    "db_availability_type": "ZONAL",
    "db_version": "POSTGRES_16",
    "redis_tier": "BASIC",
    "redis_memory_size_gb": 1,
    "outbox_mode": "polling",
    "deletion_protection": False,
}
REQUIRED_VARIABLES = {"project_id", "image"}
CONTRACT_OUTPUTS = {
    "database_endpoint",
    "redis_endpoint",
    "worker_service_name",
    "database_url",
    "redis_url",
    "log_url",
    "log_filter",
}
SENSITIVE_OUTPUTS = {"database_url", "redis_url"}

_BLOCK = re.compile(r'^(variable|output)\s+"([^"]+)"\s*\{(.*?)^\}', re.MULTILINE | re.DOTALL)
_DEFAULT = re.compile(r"^\s{2}default\s*=\s*(.+?)\s*$", re.MULTILINE)


def _blocks(kind: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for tf in MODULE.glob("*.tf"):
        for block_kind, name, body in _BLOCK.findall(tf.read_text()):
            if block_kind == kind:
                found[name] = body
    return found


def _hcl_scalar(raw: str):
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw in ("true", "false"):
        return raw == "true"
    if raw == "null":
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def _defaults() -> dict[str, object]:
    defaults: dict[str, object] = {}
    for name, body in _blocks("variable").items():
        match = _DEFAULT.search(body)
        if match:
            defaults[name] = _hcl_scalar(match.group(1))
    return defaults


def _gib(quantity: str) -> float:
    match = re.fullmatch(r"([0-9.]+)(Mi|Gi)?", quantity)
    assert match, quantity
    value = float(match.group(1))
    return value / 1024 if match.group(2) == "Mi" else value


@pytest.fixture(scope="module")
def cost() -> dict:
    return json.loads((MODULE / "cost.json").read_text())


class TestLayout:
    def test_module_files_exist(self):
        for name in (
            "versions.tf",
            "variables.tf",
            "main.tf",
            "outputs.tf",
            "README.md",
            "cost.json",
            "examples/minimal.tfvars",
            ".terraform.lock.hcl",
        ):
            assert (MODULE / name).is_file(), name

    def test_module_ships_in_package_data(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text()
        assert '"deployment/resources/**/*"' in pyproject
        assert '"deployment/resources/**/.*"' in pyproject  # .terraform.lock.hcl
        assert MODULE.is_relative_to(RESOURCES)

    def test_terraform_working_dir_is_ignored(self):
        lines = (REPO_ROOT / ".gitignore").read_text().splitlines()
        assert ".terraform/" in lines
        assert "*.tfstate" in lines

    def test_provider_pins(self):
        versions = (MODULE / "versions.tf").read_text()
        assert 'required_version = ">= 1.6"' in versions
        assert "hashicorp/random" in versions
        pinned_major(MODULE, "google")  # any major, as long as versions.tf and the lock agree
        pinned_major(MODULE, "random")


class TestContract:
    def test_contract_variables_and_defaults(self):
        variables = _blocks("variable")
        defaults = _defaults()
        for name, default in CONTRACT_VARIABLES.items():
            assert name in variables, name
            if name in REQUIRED_VARIABLES:
                assert name not in defaults, f"{name} must be required"
            elif default is not None:
                assert defaults.get(name) == default, name

    def test_only_project_and_image_are_required(self):
        required = set(_blocks("variable")) - set(_defaults())
        assert required == REQUIRED_VARIABLES

    def test_outbox_mode_is_validated(self):
        body = _blocks("variable")["outbox_mode"]
        assert "validation" in body
        assert '["polling", "cdc"]' in body

    def test_outputs(self):
        outputs = _blocks("output")
        assert set(outputs) >= CONTRACT_OUTPUTS
        for name in SENSITIVE_OUTPUTS:
            assert "sensitive   = true" in outputs[name], name

    def test_every_referenced_variable_is_declared(self):
        declared = set(_blocks("variable"))
        text = "\n".join(p.read_text() for p in MODULE.glob("*.tf"))
        referenced = set(re.findall(r"\bvar\.([a-z_][a-z0-9_]*)", text))
        assert referenced <= declared, referenced - declared

    def test_example_sets_only_declared_variables(self):
        declared = set(_blocks("variable"))
        example = (MODULE / "examples" / "minimal.tfvars").read_text()
        keys = set(re.findall(r"^([a-z_]+)\s*=", example, re.MULTILINE))
        assert keys >= REQUIRED_VARIABLES
        assert keys <= declared, keys - declared

    def test_security_settings(self):
        text = "\n".join(p.read_text() for p in MODULE.glob("*.tf"))
        assert "ipv4_enabled    = false" in text
        assert "auth_enabled       = true" in text
        assert "roles/secretmanager.secretAccessor" in text
        assert "roles/cloudsql.client" in text
        assert "disable_on_destroy = false" in text
        assert "google_cloud_run_v2_worker_pool" in text
        assert '"cloudsql.logical_decoding"' in text


class TestCostJson:
    def test_top_level_schema(self, cost):
        assert cost["provider"] == "gcp"
        assert cost["currency"] == "USD"
        assert cost["region"] == "us-central1"
        assert re.fullmatch(r"\d{4}-\d{2}", cost["priced_at"])
        assert cost["source"]
        assert cost["notes"]
        for fixed in cost["fixed"]:
            assert fixed["label"]
            assert isinstance(fixed["monthly"], int | float)

    def test_items_reference_declared_variables(self, cost):
        declared = set(_blocks("variable"))
        for item in cost["items"]:
            assert item["label"]
            assert item["prices"], item["label"]
            assert all(isinstance(v, int | float) and v >= 0 for v in item["prices"].values())
            for key in (
                "variable",
                "quantity_variable",
                "multiplier_variable",
                "per_unit_variable",
            ):
                if item.get(key) is not None:
                    assert item[key] in declared, (item["label"], item[key])
            if item.get("variable") is None:
                assert set(item["prices"]) == {"*"}, item["label"]
            if item.get("per_unit_variable") is not None:
                assert item["per_unit_divisor"] > 0
            if item.get("multiplier_variable") is not None:
                assert item["multipliers"], item["label"]

    def test_tier_choices_are_priced(self, cost):
        by_variable = {i["variable"]: i for i in cost["items"] if i.get("variable")}
        assert len(by_variable["db_tier"]["prices"]) >= 3
        assert set(by_variable["redis_tier"]["prices"]) == {"BASIC", "STANDARD_HA"}

    def test_default_sizing_is_priced(self, cost):
        defaults = _defaults()
        total = sum(f["monthly"] for f in cost["fixed"])
        for item in cost["items"]:
            variable = item.get("variable")
            price = item["prices"]["*"] if variable is None else item["prices"][defaults[variable]]
            if item.get("quantity_variable"):
                price *= float(defaults[item["quantity_variable"]])  # type: ignore[arg-type]
            if item.get("per_unit_variable"):
                raw = str(defaults[item["per_unit_variable"]])
                value = _gib(raw) if item.get("per_unit_unit") == "GiB" else float(raw)
                price *= value / item["per_unit_divisor"]
            if item.get("multiplier_variable"):
                price *= item["multipliers"].get(defaults[item["multiplier_variable"]], 1)
            total += price
        assert 50 < total < 200, total

    def test_multipliers_cover_validated_values(self, cost):
        for item in cost["items"]:
            if item.get("multiplier_variable") == "db_availability_type":
                assert item["multipliers"] == {"ZONAL": 1, "REGIONAL": 2}


def _terraform_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    Path(env["XDG_RUNTIME_DIR"]).mkdir(parents=True, exist_ok=True)
    env["TF_IN_AUTOMATION"] = "1"
    # `terraform test` uses mocked providers; make sure no real Google credentials
    # (ADC, gcloud config, inline JSON) could be picked up anyway.
    env["GOOGLE_APPLICATION_CREDENTIALS"] = os.devnull
    env["CLOUDSDK_CONFIG"] = str(tmp_path / "gcloud")
    for name in ("GOOGLE_CREDENTIALS", "GOOGLE_OAUTH_ACCESS_TOKEN", "GOOGLE_CLOUD_KEYFILE_JSON"):
        env.pop(name, None)
    return env


@pytest.mark.slow
@pytest.mark.skipif(
    shutil.which("terraform") is None or bool(os.environ.get("SAGAZ_OFFLINE")),
    reason="needs terraform and network access for provider download (unset SAGAZ_OFFLINE)",
)
def test_terraform_validate_and_mocked_plan(tmp_path):
    workdir = tmp_path / "gcp"
    shutil.copytree(MODULE, workdir, ignore=shutil.ignore_patterns(".terraform"))
    env = _terraform_env(tmp_path)

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["terraform", *args, "-no-color"],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )

    init = run("init", "-backend=false", "-input=false")
    if init.returncode != 0:
        # Provider downloads need the Terraform registry; like the AWS test, an
        # unreachable registry is an environment problem, not a module failure.
        pytest.skip(f"terraform init failed (offline?): {init.stderr[-500:]}")
    for args in (("validate",), ("fmt", "-check", "-recursive"), ("test",)):
        result = run(*args)
        assert result.returncode == 0, result.stdout + result.stderr
