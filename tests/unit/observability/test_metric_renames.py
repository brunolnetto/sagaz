"""Every metric is named ``sagaz_*``; the old names stay until 3.0 (#572)."""

from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from sagaz.core.types import SagaStatus
from sagaz.observability._renamed import OLD_NAMES_ENV, emit_old_names, renamed
from sagaz.observability.monitoring.prometheus import PrometheusMetrics


def samples(registry: CollectorRegistry) -> dict[str, float]:
    text = generate_latest(registry).decode()
    return {
        line.rsplit(" ", 1)[0]: float(line.rsplit(" ", 1)[1])
        for line in text.splitlines()
        if line and not line.startswith("#") and "_created" not in line
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), ("1", True), ("0", False), ("false", False), ("No", False)],
)
def test_old_names_are_on_unless_turned_off(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(OLD_NAMES_ENV, raising=False)
    else:
        monkeypatch.setenv(OLD_NAMES_ENV, value)
    assert emit_old_names() is expected


def test_a_renamed_metric_records_under_both_names(monkeypatch):
    monkeypatch.delenv(OLD_NAMES_ENV, raising=False)
    registry = CollectorRegistry()
    counter = renamed(
        Counter, "sagaz_outbox_x_total", "outbox_x_total", "x", ["k"], registry=registry
    )
    histogram = renamed(
        Histogram, "sagaz_outbox_t_seconds", "outbox_t_seconds", "t", registry=registry
    )
    gauge = renamed(Gauge, "sagaz_outbox_g", "outbox_g", "g", registry=registry)

    counter.labels(k="a").inc(2)
    with histogram.time():
        pass
    histogram.observe(0.5)
    gauge.set(5)
    gauge.inc()
    gauge.dec(2)

    got = samples(registry)
    assert got['sagaz_outbox_x_total{k="a"}'] == got['outbox_x_total{k="a"}'] == 2
    assert got["sagaz_outbox_t_seconds_count"] == got["outbox_t_seconds_count"] == 2
    assert got["sagaz_outbox_g"] == got["outbox_g"] == 4


def test_turned_off_only_the_new_name_exists(monkeypatch):
    monkeypatch.setenv(OLD_NAMES_ENV, "0")
    registry = CollectorRegistry()
    renamed(Counter, "sagaz_outbox_x_total", "outbox_x_total", "x", registry=registry).inc()
    assert set(samples(registry)) == {"sagaz_outbox_x_total"}


def test_prometheus_metrics_default_to_sagaz_saga_and_keep_saga(monkeypatch):
    monkeypatch.delenv(OLD_NAMES_ENV, raising=False)
    registry = CollectorRegistry()
    PrometheusMetrics(registry=registry).record_execution("order", SagaStatus.COMPLETED, 0.2)
    got = samples(registry)
    new = 'sagaz_saga_execution_total{saga_name="order",status="completed"}'
    assert got[new] == got[new.replace("sagaz_saga_", "saga_")] == 1


def test_a_custom_prefix_is_left_alone(monkeypatch):
    monkeypatch.delenv(OLD_NAMES_ENV, raising=False)
    registry = CollectorRegistry()
    PrometheusMetrics(prefix="shop", registry=registry).record_execution(
        "order", SagaStatus.COMPLETED, 0.2
    )
    assert {name.split("{")[0] for name in samples(registry)} <= {
        "shop_execution_total",
        "shop_execution_duration_seconds_bucket",
        "shop_execution_duration_seconds_count",
        "shop_execution_duration_seconds_sum",
        "shop_active_count",
    }


def test_the_library_registers_every_outbox_and_inbox_metric_as_sagaz():
    from prometheus_client import REGISTRY

    import sagaz.core.outbox.consumer_inbox
    import sagaz.core.outbox.optimistic_publisher
    import sagaz.core.outbox.worker  # noqa: F401 - registers the worker's metrics

    names = {metric.name for metric in REGISTRY.collect()}
    new = {name for name in names if name.startswith(("sagaz_outbox_", "sagaz_inbox_"))}
    assert len(new) == 18
    old = {name for name in names if name.startswith(("outbox_", "consumer_inbox_"))}
    assert old == {
        name.removeprefix("sagaz_").replace("inbox_", "consumer_inbox_", 1) for name in new
    }
