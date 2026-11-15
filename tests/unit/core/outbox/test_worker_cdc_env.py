"""Environment-driven CDC mode of the outbox worker entry point (ADR-011, #50)."""

from __future__ import annotations

import pytest

from sagaz.core.outbox._worker_bootstrap import cdc_config_from_env, get_cdc_source
from sagaz.integrations.cdc import DebeziumKafkaSource, PgLogicalSource

CDC_VARS = (
    "SAGAZ_OUTBOX_MODE",
    "SAGAZ_CDC_SOURCE",
    "SAGAZ_CDC_DSN",
    "DATABASE_URL",
    "SAGAZ_CDC_SLOT",
    "SAGAZ_CDC_PUBLICATION",
    "KAFKA_BOOTSTRAP_SERVERS",
    "SAGAZ_CDC_TOPIC_PREFIX",
    "SAGAZ_CDC_GROUP_ID",
    "SAGAZ_CDC_SWEEP_INTERVAL",
    "SAGAZ_CDC_SWEEP_MIN_AGE",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in CDC_VARS:
        monkeypatch.delenv(name, raising=False)


def test_polling_is_the_default():
    assert get_cdc_source() is None


def test_pg_logical_source_from_database_url(monkeypatch):
    monkeypatch.setenv("SAGAZ_OUTBOX_MODE", "CDC")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app@db/sagas")
    monkeypatch.setenv("SAGAZ_CDC_SLOT", "orders_slot")

    source = get_cdc_source()

    assert isinstance(source, PgLogicalSource)
    assert (source.dsn, source.slot) == ("postgresql://app@db/sagas", "orders_slot")


def test_cdc_dsn_takes_precedence(monkeypatch):
    monkeypatch.setenv("SAGAZ_OUTBOX_MODE", "cdc")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app@db/sagas")
    monkeypatch.setenv("SAGAZ_CDC_DSN", "postgresql://replicator@db/sagas")
    assert get_cdc_source().dsn == "postgresql://replicator@db/sagas"


def test_debezium_source(monkeypatch):
    monkeypatch.setenv("SAGAZ_OUTBOX_MODE", "cdc")
    monkeypatch.setenv("SAGAZ_CDC_SOURCE", "debezium")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.setenv("SAGAZ_CDC_TOPIC_PREFIX", "shop")

    source = get_cdc_source()

    assert isinstance(source, DebeziumKafkaSource)
    assert source.topic == "shop.public.saga_outbox"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"SAGAZ_OUTBOX_MODE": "stream"}, "SAGAZ_OUTBOX_MODE must be"),
        ({"SAGAZ_OUTBOX_MODE": "cdc"}, "SAGAZ_CDC_DSN or DATABASE_URL is required"),
        ({"SAGAZ_OUTBOX_MODE": "cdc", "SAGAZ_CDC_SOURCE": "dms"}, "SAGAZ_CDC_SOURCE must be"),
    ],
)
def test_invalid_configuration_exits(monkeypatch, caplog, env, message):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(SystemExit):
        get_cdc_source()
    assert message in caplog.text


def test_sweep_configuration(monkeypatch):
    assert cdc_config_from_env() == {
        "cdc_sweep_interval_seconds": 30.0,
        "cdc_sweep_min_age_seconds": 30.0,
    }
    monkeypatch.setenv("SAGAZ_CDC_SWEEP_INTERVAL", "0")
    monkeypatch.setenv("SAGAZ_CDC_SWEEP_MIN_AGE", "5")
    assert cdc_config_from_env() == {
        "cdc_sweep_interval_seconds": None,
        "cdc_sweep_min_age_seconds": 5.0,
    }
