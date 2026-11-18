"""The Helm chart for the outbox worker (``sagaz/deployment/resources/charts/sagaz``).

Rendering tests run ``helm template`` and are skipped when ``helm`` is not on PATH;
the metadata tests need no tools beyond PyYAML.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHART = ROOT / "sagaz" / "deployment" / "resources" / "charts" / "sagaz"
CI_VALUES = sorted((CHART / "ci").glob("*.yaml"))
HELM = shutil.which("helm")

REQUIRED = ["database.url=postgresql://u:p@db:5432/sagaz", "broker.url=kafka:9092"]

needs_helm = pytest.mark.skipif(HELM is None, reason="helm is not installed")


def _render(*sets: str, values: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [str(HELM), "template", "sagaz", str(CHART), "--namespace", "sagaz"]
    if values is not None:
        cmd += ["-f", str(values)]
    for item in sets:
        cmd += ["--set", item]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)


def _objects(*sets: str, values: Path | None = None) -> dict[str, dict[str, Any]]:
    result = _render(*sets, values=values)
    assert result.returncode == 0, result.stderr
    docs = [d for d in yaml.safe_load_all(result.stdout) if d]
    by_kind: dict[str, dict[str, Any]] = {}
    for doc in docs:
        assert doc["kind"] not in by_kind, f"duplicate {doc['kind']}"
        by_kind[doc["kind"]] = doc
    return by_kind


def _container(objs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    containers = objs["Deployment"]["spec"]["template"]["spec"]["containers"]
    assert len(containers) == 1
    return containers[0]


def _env(objs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Container env by name, plus the ConfigMap's data (plain values)."""
    env: dict[str, Any] = dict(objs["ConfigMap"]["data"])
    for var in _container(objs)["env"]:
        env[var["name"]] = var.get("value", var.get("valueFrom"))
    return env


def _secret_ref(value: Any) -> tuple[str, str]:
    ref = value["secretKeyRef"]
    return ref["name"], ref["key"]


# --- metadata (no helm needed) ----------------------------------------------


def test_chart_metadata_matches_the_package_version() -> None:
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert chart["apiVersion"] == "v2"
    assert chart["name"] == "sagaz"
    assert chart["version"] == "0.1.0"
    assert chart["appVersion"] == pyproject["project"]["version"]


def test_chart_ships_in_the_package() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["sagaz"]
    assert "deployment/resources/**/*" in package_data
    assert (CHART / "templates" / "_helpers.tpl").is_file()


def test_values_schema_accepts_default_and_ci_values() -> None:
    schema = json.loads((CHART / "values.schema.json").read_text(encoding="utf-8"))
    defaults = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))

    assert schema["type"] == "object"
    assert set(schema["required"]) <= set(defaults)
    assert set(defaults) <= set(schema["properties"]), "undocumented top-level value"
    assert CI_VALUES, "ci/ values files are missing"

    jsonschema = pytest.importorskip("jsonschema")
    validator = jsonschema.Draft7Validator(schema)
    validator.validate(defaults)
    for path in CI_VALUES:
        overrides = yaml.safe_load(path.read_text(encoding="utf-8"))
        validator.validate(_merge(defaults, overrides))
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(_merge(defaults, {"broker": {"type": "nats"}}))


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# --- rendering ---------------------------------------------------------------


@needs_helm
@pytest.mark.parametrize("values", CI_VALUES, ids=lambda p: p.stem)
def test_ci_variants_lint_and_render(values: Path) -> None:
    lint = subprocess.run(
        [str(HELM), "lint", "--strict", str(CHART), "-f", str(values)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr
    assert "Deployment" in _objects(values=values)


@needs_helm
def test_rendering_requires_database_and_broker() -> None:
    result = _render()
    assert result.returncode != 0
    assert "database.url or database.existingSecret" in result.stderr

    result = _render(REQUIRED[0])
    assert result.returncode != 0
    assert "broker.url or broker.existingSecret" in result.stderr


@needs_helm
def test_image_tag_defaults_to_app_version() -> None:
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text(encoding="utf-8"))
    objs = _objects(*REQUIRED, "image.repository=registry.example/sagaz")
    assert _container(objs)["image"] == f"registry.example/sagaz:{chart['appVersion']}"

    objs = _objects(*REQUIRED, "image.repository=registry.example/sagaz", "image.tag=dev")
    assert _container(objs)["image"] == "registry.example/sagaz:dev"


@needs_helm
def test_worker_runs_the_outbox_entry_point_with_its_pod_name_as_id() -> None:
    objs = _objects(*REQUIRED)
    container = _container(objs)
    assert container["command"] == ["python", "-m", "sagaz.core.outbox.worker"]

    env = _env(objs)
    assert env["WORKER_ID"] == {"fieldRef": {"fieldPath": "metadata.name"}}
    assert env["BATCH_SIZE"] == "100"
    assert env["POLL_INTERVAL"] == "1"
    assert env["MAX_RETRIES"] == "5"
    assert env["LOG_LEVEL"] == "INFO"
    assert env["SAGAZ_OUTBOX_MODE"] == "polling"
    assert not any(name.startswith("SAGAZ_CDC_") for name in env)


@needs_helm
@pytest.mark.parametrize(
    ("broker", "env_name"),
    [("redis", "REDIS_URL"), ("kafka", "KAFKA_BOOTSTRAP_SERVERS"), ("rabbitmq", "RABBITMQ_URL")],
)
def test_broker_url_env_follows_broker_type(broker: str, env_name: str) -> None:
    objs = _objects(*REQUIRED, f"broker.type={broker}")
    env = _env(objs)

    assert env["BROKER_TYPE"] == broker
    assert _secret_ref(env[env_name]) == ("sagaz", "broker-url")
    assert _secret_ref(env["BROKER_URL"]) == ("sagaz", "broker-url")
    assert _secret_ref(env["DATABASE_URL"]) == ("sagaz", "database-url")
    others = {"REDIS_URL", "KAFKA_BOOTSTRAP_SERVERS", "RABBITMQ_URL"} - {env_name}
    assert not others & set(env)
    assert ("RABBITMQ_EXCHANGE" in env) == (broker == "rabbitmq")


@needs_helm
def test_plain_urls_go_into_the_charts_secret() -> None:
    objs = _objects(*REQUIRED)
    secret = objs["Secret"]
    assert secret["metadata"]["name"] == "sagaz"
    assert set(secret["data"]) == {"database-url", "broker-url"}
    # Credentials never land in the ConfigMap.
    assert "postgresql://" not in json.dumps(objs["ConfigMap"])


@needs_helm
def test_existing_secrets_are_referenced_and_no_secret_is_rendered() -> None:
    objs = _objects(values=CHART / "ci" / "existing-secret.yaml")
    assert "Secret" not in objs

    env = _env(objs)
    assert _secret_ref(env["DATABASE_URL"]) == ("sagaz-db-credentials", "connection-string")
    assert _secret_ref(env["RABBITMQ_URL"]) == ("sagaz-broker-credentials", "rabbitmq-url")


@needs_helm
def test_hpa_only_in_polling_mode() -> None:
    objs = _objects(values=CHART / "ci" / "polling-redis.yaml")
    hpa = objs["HorizontalPodAutoscaler"]
    assert hpa["spec"]["minReplicas"] == 2
    assert hpa["spec"]["scaleTargetRef"]["name"] == objs["Deployment"]["metadata"]["name"]
    assert "replicas" not in objs["Deployment"]["spec"]

    assert "HorizontalPodAutoscaler" not in _objects(*REQUIRED)

    for source in ("pg_logical", "debezium"):
        result = _render(
            *REQUIRED,
            "outbox.mode=cdc",
            f"outbox.cdc.source={source}",
            "autoscaling.enabled=true",
        )
        assert result.returncode != 0
        assert "autoscaling.enabled is supported in outbox.mode=polling only" in result.stderr


@needs_helm
def test_cdc_pg_logical_runs_a_single_recreated_replica() -> None:
    objs = _objects(values=CHART / "ci" / "cdc-pglogical.yaml")
    deployment = objs["Deployment"]
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"] == {"type": "Recreate"}

    env = _env(objs)
    assert env["SAGAZ_OUTBOX_MODE"] == "cdc"
    assert env["SAGAZ_CDC_SOURCE"] == "pg_logical"
    assert env["SAGAZ_CDC_SLOT"] == "sagaz_outbox"
    assert env["SAGAZ_CDC_PUBLICATION"] == "sagaz_outbox_pub"
    assert env["SAGAZ_CDC_SWEEP_INTERVAL"] == "30"
    assert env["SAGAZ_CDC_SWEEP_MIN_AGE"] == "30"
    assert _secret_ref(env["SAGAZ_CDC_DSN"]) == ("sagaz", "cdc-dsn")
    assert "cdc-dsn" in objs["Secret"]["data"]


@needs_helm
def test_cdc_pg_logical_rejects_more_than_one_replica() -> None:
    result = _render("replicaCount=2", values=CHART / "ci" / "cdc-pglogical.yaml")
    assert result.returncode != 0
    assert "requires replicaCount=1" in result.stderr


@needs_helm
def test_cdc_debezium_scales_and_reads_its_own_kafka() -> None:
    objs = _objects(values=CHART / "ci" / "cdc-debezium.yaml")
    assert objs["Deployment"]["spec"]["replicas"] == 2
    assert objs["Deployment"]["spec"]["strategy"]["type"] == "RollingUpdate"

    env = _env(objs)
    assert env["SAGAZ_CDC_SOURCE"] == "debezium"
    assert env["KAFKA_BOOTSTRAP_SERVERS"] == "kafka:9092"
    assert env["SAGAZ_CDC_GROUP_ID"] == "sagaz-cdc"
    assert "SAGAZ_CDC_SLOT" not in env
    assert "SAGAZ_CDC_DSN" not in env

    result = _render(
        *REQUIRED, "broker.type=redis", "outbox.mode=cdc", "outbox.cdc.source=debezium"
    )
    assert result.returncode != 0
    assert "outbox.cdc.debezium.bootstrapServers" in result.stderr


@needs_helm
def test_security_context_is_restricted() -> None:
    objs = _objects(*REQUIRED)
    pod = objs["Deployment"]["spec"]["template"]["spec"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["runAsUser"] == 1000
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert pod["automountServiceAccountToken"] is False

    container = _container(objs)["securityContext"]
    assert container["allowPrivilegeEscalation"] is False
    assert container["readOnlyRootFilesystem"] is True
    assert container["capabilities"] == {"drop": ["ALL"]}
    mounts = {m["mountPath"] for m in _container(objs)["volumeMounts"]}
    assert "/tmp" in mounts


@needs_helm
def test_metrics_objects_are_opt_in() -> None:
    objs = _objects(*REQUIRED)
    assert "Service" not in objs
    assert "ports" not in _container(objs)

    objs = _objects(values=CHART / "ci" / "kafka.yaml")
    assert objs["Service"]["spec"]["ports"][0]["port"] == 8000
    assert objs["ServiceMonitor"]["spec"]["endpoints"][0]["path"] == "/metrics"
    assert objs["PodDisruptionBudget"]["spec"] == {
        "minAvailable": 2,
        "selector": objs["Deployment"]["spec"]["selector"],
    }
