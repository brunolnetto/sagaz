"""Static checks of the AWS Terraform module shipped for ``sagaz deploy --provider aws``.

The first group needs neither network nor terraform; ``terraform validate`` runs
only when the binary is installed and ``SAGAZ_OFFLINE`` is not set.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import sagaz
from tests.unit.deployment._terraform_pins import pinned_major

PACKAGE_DIR = Path(sagaz.__file__).parent
MODULE_DIR = PACKAGE_DIR / "deployment" / "resources" / "infra" / "aws"

CONTRACT_VARIABLES = {
    "name",
    "environment",
    "region",
    "tags",
    "image",
    "worker_count",
    "worker_cpu",
    "worker_memory",
    "db_instance_class",
    "db_storage_gb",
    "db_multi_az",
    "db_engine_version",
    "redis_node_type",
    "outbox_mode",
    "vpc_id",
    "subnet_ids",
}
CONTRACT_OUTPUTS = {
    "database_endpoint",
    "redis_endpoint",
    "worker_service_name",
    "cluster_name",
    "database_url",
    "redis_url",
    "log_group",
}
SENSITIVE_OUTPUTS = {"database_url", "redis_url"}
VARIABLE_KEYS = ("variable", "quantity_variable", "per_unit_variable", "multiplier_variable")

_BLOCK = re.compile(r'^(variable|output) "([^"]+)" \{\n(.*?)^\}', re.MULTILINE | re.DOTALL)
_DEFAULT = re.compile(r"^  default\s*=\s*(.+)$", re.MULTILINE)


def _blocks(filename: str, kind: str) -> dict[str, str]:
    text = (MODULE_DIR / filename).read_text()
    return {name: body for k, name, body in _BLOCK.findall(text) if k == kind}


def _variables() -> dict[str, str]:
    return _blocks("variables.tf", "variable")


def _default(body: str):
    """The default of a variable block as a Python value (scalars only), or ``...`` if absent."""
    match = _DEFAULT.search(body)
    if not match:
        return ...
    raw = match.group(1).strip()
    if raw == "null":
        return None
    if raw in ("true", "false"):
        return raw == "true"
    if raw.startswith('"'):
        return json.loads(raw)
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return raw  # list/map literal, not needed here


def _cost() -> dict:
    return json.loads((MODULE_DIR / "cost.json").read_text())


def test_module_ships_in_package():
    assert MODULE_DIR.is_dir()
    assert MODULE_DIR.relative_to(PACKAGE_DIR / "deployment" / "resources")
    for name in (
        "versions.tf",
        "variables.tf",
        "main.tf",
        "outputs.tf",
        "README.md",
        "cost.json",
        "examples/minimal.tfvars",
    ):
        assert (MODULE_DIR / name).is_file(), name

    pyproject = (PACKAGE_DIR.parent / "pyproject.toml").read_text()
    assert '"deployment/resources/**/*"' in pyproject


def test_versions_pin_providers():
    text = (MODULE_DIR / "versions.tf").read_text()
    assert re.search(r'required_version\s*=\s*">=\s*1\.6"', text)
    pinned_major(MODULE_DIR, "aws")  # any major, as long as versions.tf and the lock agree
    assert 'source  = "hashicorp/random"' in text


def test_contract_variables_declared():
    variables = _variables()
    missing = CONTRACT_VARIABLES - variables.keys()
    assert not missing, f"variables.tf lacks {sorted(missing)}"

    # image is the only required input
    required = {name for name, body in variables.items() if _default(body) is ...}
    assert required == {"image"}


def test_contract_defaults():
    defaults = {name: _default(body) for name, body in _variables().items()}
    assert defaults["name"] == "sagaz"
    assert defaults["environment"] == "prod"
    assert defaults["region"] == "us-east-1"
    assert defaults["worker_count"] == 1
    assert defaults["worker_cpu"] == 256
    assert defaults["worker_memory"] == 512
    assert defaults["db_instance_class"] == "db.t4g.micro"
    assert defaults["db_storage_gb"] == 20
    assert defaults["db_multi_az"] is False
    assert str(defaults["db_engine_version"]).startswith("16.")
    assert defaults["redis_node_type"] == "cache.t4g.micro"
    assert defaults["outbox_mode"] == "polling"
    assert defaults["vpc_id"] is None
    assert defaults["subnet_ids"] is None


def test_outbox_mode_is_validated():
    body = _variables()["outbox_mode"]
    assert "validation" in body
    assert '"polling"' in body
    assert '"cdc"' in body


def test_contract_outputs_declared():
    outputs = _blocks("outputs.tf", "output")
    missing = CONTRACT_OUTPUTS - outputs.keys()
    assert not missing, f"outputs.tf lacks {sorted(missing)}"
    for name in SENSITIVE_OUTPUTS:
        assert re.search(r"sensitive\s*=\s*true", outputs[name]), name


def test_secrets_injected_not_plain_env():
    worker = (MODULE_DIR / "worker.tf").read_text()
    assert '{ name = "DATABASE_URL", valueFrom' in worker
    assert '{ name = "REDIS_URL", valueFrom' in worker
    assert 'BROKER_TYPE   = "redis"' in worker


def test_cost_schema():
    cost = _cost()
    for key in ("provider", "currency", "region", "priced_at", "source", "items", "fixed", "notes"):
        assert key in cost, key
    assert cost["provider"] == "aws"
    assert cost["currency"] == "USD"
    assert re.fullmatch(r"\d{4}-\d{2}", cost["priced_at"])
    assert cost["items"]
    for item in cost["items"]:
        assert isinstance(item["label"], str)
        assert item["label"]
        assert item["prices"], item["label"]
        assert all(isinstance(p, int | float) and p >= 0 for p in item["prices"].values())
        if item.get("per_unit_variable"):
            assert item["per_unit_divisor"] > 0
    for fixed in cost["fixed"]:
        assert isinstance(fixed["label"], str)
        assert isinstance(fixed["monthly"], int | float)
    assert all(isinstance(note, str) for note in cost["notes"])


def test_cost_variables_exist_and_defaults_are_priced():
    variables = _variables()
    for item in _cost()["items"]:
        for key in VARIABLE_KEYS:
            ref = item.get(key)
            if ref is not None:
                assert ref in variables, f"{item['label']}: {key}={ref} not in variables.tf"
        sizing = item.get("variable")
        if sizing is None:
            assert "*" in item["prices"], item["label"]
        else:
            default = _default(variables[sizing])
            assert default in item["prices"], f"default {sizing}={default} has no price"


def test_cost_prices_several_sizes():
    by_variable = {i["variable"]: i for i in _cost()["items"] if i.get("variable")}
    assert len(by_variable["db_instance_class"]["prices"]) >= 3
    assert len(by_variable["redis_node_type"]["prices"]) >= 3


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not installed")
@pytest.mark.skipif(
    os.getenv("SAGAZ_OFFLINE") == "1", reason="SAGAZ_OFFLINE=1 (init downloads providers)"
)
def test_terraform_validate(tmp_path):
    # Copy the module so the test never writes .terraform/ into the package tree.
    workdir = tmp_path / "aws"
    shutil.copytree(MODULE_DIR, workdir, ignore=shutil.ignore_patterns(".terraform"))
    env = {**os.environ, "TF_IN_AUTOMATION": "1"}
    env.setdefault("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    Path(env["XDG_RUNTIME_DIR"]).mkdir(parents=True, exist_ok=True)

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["terraform", *args],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )

    init = run("init", "-backend=false", "-input=false", "-no-color")
    if init.returncode != 0:
        pytest.skip(f"terraform init failed (offline?): {init.stderr[-500:]}")
    validate = run("validate", "-no-color")
    assert validate.returncode == 0, validate.stdout + validate.stderr
    fmt = run("fmt", "-check", "-recursive")
    assert fmt.returncode == 0, fmt.stdout
