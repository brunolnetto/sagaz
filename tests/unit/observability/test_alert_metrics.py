"""Every metric an alert rule or a dashboard queries is one sagaz registers (#617).

Four Kubernetes alerts queried metrics sagaz never emitted, so they could never fire,
and nothing noticed. This test reads every PromQL expression the repository ships
(alert rules, and the Prometheus panels of the Grafana dashboards) and checks each
metric name against the metrics the library registers.
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

pytest.importorskip("prometheus_client")

ROOT = Path(__file__).resolve().parents[3]
RESOURCES = ROOT / "sagaz" / "deployment" / "resources"

RULE_FILES = [
    RESOURCES / "k8s" / "monitoring" / "alerts" / "postgres-alerts.yaml",
    RESOURCES / "k8s" / "monitoring" / "alertmanager-rules.yml",
    ROOT / "docs" / "monitoring" / "alertmanager-rules.yml",
]
DASHBOARD_FILES = sorted(
    path for path in RESOURCES.rglob("*.json") if '"panels"' in path.read_text(encoding="utf-8")
)

#: Metrics other exporters own: the dashboards and alerts may query them.
EXTERNAL = {
    "up": "Prometheus's own scrape health",
    "kube_deployment_spec_replicas": "kube-state-metrics",
    "container_cpu_usage_seconds_total": "cAdvisor, through the kubelet",
    "container_memory_working_set_bytes": "cAdvisor, through the kubelet",
    "container_spec_memory_limit_bytes": "cAdvisor, through the kubelet",
}

#: Metrics shipped rules still query that sagaz does not emit yet: #637 adds them or
#: removes the rule. This list only shrinks (see the last test).
NOT_EMITTED_YET = {
    "sagaz_saga_running_duration_seconds": "SagaStuckExecution: a stalled-saga signal",
    "sagaz_saga_started_total": "SagaNoActivity",
    "sagaz_dlq_oldest_message_age_seconds": "DLQStaleMessages",
    "sagaz_outbox_lag_seconds": "OutboxHighLag",
    "sagaz_cdc_connector_status": "CDCConnectorDown",
    "sagaz_db_pool_available": "DatabasePoolExhausted",
    "sagaz_broker_connection_errors_total": "BrokerConnectionIssues",
}

#: Modules that create sagaz's metrics when imported.
METRIC_MODULES = [
    "sagaz.core.outbox._worker_metrics",
    "sagaz.core.outbox._worker_cdc",
    "sagaz.core.outbox.consumer_inbox",
    "sagaz.core.outbox.optimistic_publisher",
    "sagaz.choreography._dispatch",
    "sagaz.core.regions.coordinator",
    "sagaz.core.storage.event_store.recorder",
]

_KEYWORDS = {
    "and", "or", "unless", "bool", "offset", "by", "without", "on", "ignoring",
    "group_left", "group_right", "inf", "nan",
}  # fmt: skip
_SUFFIXES = {
    "counter": ("_total", "_created"),
    "histogram": ("_bucket", "_sum", "_count", "_created"),
    "summary": ("_sum", "_count", "_created"),
}


class _NoHistory:
    def read(self) -> Any:
        msg = "no Iceberg table in this test"
        raise LookupError(msg)


class _IdleExporter:
    def metrics(self) -> dict[str, Any]:
        return {"exporter": "test", "exported": 0, "errors": 0, "lag_seconds": None}


def registered_metrics() -> set[str]:
    """Every series name the library can emit."""
    from prometheus_client import REGISTRY, CollectorRegistry

    from sagaz.integrations.iceberg_metrics import ExporterCollector, IcebergFlowCollector
    from sagaz.observability.monitoring.prometheus import PrometheusMetrics

    for module in METRIC_MODULES:
        importlib.import_module(module)
    own = CollectorRegistry()
    PrometheusMetrics(registry=own)
    families = [
        *REGISTRY.collect(),
        *own.collect(),
        # Collectors the analytics exporter registers; stubs give their metric families.
        *IcebergFlowCollector(_NoHistory()).collect(),
        *ExporterCollector(_IdleExporter()).collect(),
    ]
    names = set()
    for family in families:
        names.add(family.name)
        names.update(family.name + suffix for suffix in _SUFFIXES.get(family.type, ()))
    return names


def expressions(path: Path) -> Iterator[str]:
    """The PromQL expressions in a rules file or a Grafana dashboard."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        yield from _dashboard_exprs(json.loads(text))
        return
    for document in yaml.safe_load_all(text):
        if isinstance(document, dict) and document.get("kind") == "ConfigMap":
            for embedded in (document.get("data") or {}).values():
                yield from _values(yaml.safe_load(embedded), "expr")
        else:
            yield from _values(document, "expr")


def _values(node: Any, key: str) -> Iterator[str]:
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key and isinstance(value, str):
                yield value
            else:
                yield from _values(value, key)
    elif isinstance(node, list):
        for item in node:
            yield from _values(item, key)


def _dashboard_exprs(node: Any, source: str = "") -> Iterator[str]:
    """``expr`` of Prometheus targets; Loki targets (LogQL) are skipped."""
    if isinstance(node, dict):
        datasource = node.get("datasource", source)
        if isinstance(datasource, dict):
            datasource = f"{datasource.get('type', '')} {datasource.get('uid', '')}"
        datasource = str(datasource or "")
        if "loki" not in datasource.lower() and isinstance(node.get("expr"), str):
            yield node["expr"]
        for value in node.values():
            yield from _dashboard_exprs(value, datasource)
    elif isinstance(node, list):
        for item in node:
            yield from _dashboard_exprs(item, source)


def metric_names(expr: str) -> set[str]:
    """The metric names a PromQL expression selects."""
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', expr)  # strings
    text = re.sub(r"\{[^}]*\}", " ", text)  # label matchers
    text = re.sub(r"\[[^\]]*\]", " ", text)  # ranges
    text = re.sub(r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", " ", text)
    text = re.sub(r"\$\{?\w+\}?", " ", text)  # Grafana variables
    names = set()
    for match in re.finditer(r"(?<![\w.])([A-Za-z_:][\w:]*)(\s*\()?", text):
        name, call = match.groups()
        if not call and name.lower() not in _KEYWORDS:
            names.add(name)
    return names


def test_the_parser_finds_metrics_and_skips_the_rest():
    expr = (
        "histogram_quantile(0.95, sum by (le, saga_name) (rate(sagaz_saga_step_duration_seconds_bucket"
        '{status="failed", job=~"$job"}[5m]))) > 1 and on (pod) up offset 1h'
    )
    assert metric_names(expr) == {"sagaz_saga_step_duration_seconds_bucket", "up"}


def queried(path: Path) -> set[str]:
    return {name for expr in expressions(path) for name in metric_names(expr)}


#: Files with PromQL: a dashboard made only of Loki (LogQL) panels has none.
PROMQL_FILES = [path for path in RULE_FILES + DASHBOARD_FILES if queried(path)]


@pytest.fixture(scope="module")
def registered() -> set[str]:
    return registered_metrics()


@pytest.mark.parametrize("path", PROMQL_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_every_queried_metric_is_registered(path: Path, registered: set[str]):
    known = registered | set(EXTERNAL) | set(NOT_EMITTED_YET)
    assert sorted(queried(path) - known) == []


def test_the_rules_and_dashboards_are_all_checked():
    assert {path.name for path in PROMQL_FILES} >= {
        "postgres-alerts.yaml",
        "alertmanager-rules.yml",
        "main-dashboard.json",
        "outbox-dashboard.json",
    }


def test_not_emitted_yet_only_shrinks(registered: set[str]):
    everything = set().union(*(queried(path) for path in PROMQL_FILES))
    assert sorted(set(NOT_EMITTED_YET) - everything) == []  # no longer queried: remove it
    assert sorted(set(NOT_EMITTED_YET) & registered) == []  # emitted now: remove it
