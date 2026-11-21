"""``sagaz event-log`` against a SQLite event store (#57)."""

from __future__ import annotations

import asyncio
import json

import pytest
from click.testing import CliRunner

from sagaz.cli.app import cli
from sagaz.core.exceptions import SagaFailedError
from sagaz.core.storage.event_store.sqlite import SQLiteEventStore
from tests.unit.core.test_event_sourcing import make_saga


@pytest.fixture
def store_url(tmp_path):
    path = tmp_path / "events.db"

    async def record() -> None:
        async with SQLiteEventStore(str(path)) as store:
            await make_saga(store).run({"order_id": "o-1"}, saga_id="ok", tenant_context="acme")
            with pytest.raises(SagaFailedError):
                await make_saga(store, fail_charge=True).run({"order_id": "o-2"}, saga_id="bad")

    asyncio.run(record())
    return f"sqlite://{path}"


def invoke(*args):
    return CliRunner().invoke(cli, ["event-log", *args])


def test_timeline(store_url):
    result = invoke("bad", "--store-url", store_url)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "Saga bad (order, tenant default): rolled_back"
    assert "StepFailed" in lines[3]
    assert "charge  ValueError: card declined" in lines[3]
    assert lines[4].split()[3:5] == ["CompensationStarted", "charge"]
    assert lines[6].endswith("ms")


def test_tenant_and_json(store_url):
    assert invoke("ok", "--store-url", store_url).exit_code == 1  # other tenant
    result = invoke("ok", "--store-url", store_url, "--tenant", "acme", "--json")
    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert [e["sequence"] for e in document["events"]] == [1, 2, 3, 4]
    assert document["state"]["status"] == "completed"


def test_unknown_saga(store_url):
    result = invoke("missing", "--store-url", store_url)
    assert result.exit_code == 1
    assert "No events for saga 'missing'" in result.output


def test_store_url_from_env(store_url, monkeypatch):
    monkeypatch.setenv("SAGAZ_EVENT_STORE_URL", store_url)
    assert invoke("bad").exit_code == 0
