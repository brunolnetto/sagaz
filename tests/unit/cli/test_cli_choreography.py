"""``sagaz choreography status`` against a tracker's SQLite storage (#56)."""

from __future__ import annotations

import asyncio
import json

import pytest
from click.testing import CliRunner

from sagaz.cli.app import cli
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage
from tests.unit.test_choreography_compensation import Stack


@pytest.fixture
def storage_url(tmp_path):
    path = tmp_path / "choreography.db"

    async def record() -> None:
        async with SQLiteSagaStorage(str(path)) as storage:
            async with Stack(storage=storage) as stack:
                await stack.orders.begin(
                    "order.created", {"order_id": "o-1"}, correlation_id="ok", tenant_id="acme"
                )
                await stack.orders.begin(
                    "order.created",
                    {"order_id": "o-2", "amount": 500},
                    correlation_id="bad",
                    tenant_id="acme",
                )

    asyncio.run(record())
    return f"sqlite://{path}"


def _status(*args):
    return CliRunner().invoke(cli, ["choreography", "status", *args])


def test_completed_transaction(storage_url):
    result = _status("ok", "--tenant", "acme", "--storage-url", storage_url)
    assert result.exit_code == 0, result.output
    assert "Transaction ok (tenant acme): completed" in result.output
    assert "failed:" not in result.output


def test_compensated_transaction_shows_failure_and_compensations(storage_url):
    result = _status("bad", "--tenant", "acme", "--storage-url", storage_url, "--events")
    assert result.exit_code == 0, result.output
    assert "Transaction bad (tenant acme): compensated" in result.output
    assert "failed: payments on inventory.reserved (ValueError: card declined)" in result.output
    assert "compensated by inventory: order.created" in result.output
    assert "compensated by shipping: nothing to undo" in result.output
    assert "choreography.compensate" in result.output  # --events lists them


def test_json_output(storage_url):
    result = _status("bad", "--tenant", "acme", "--storage-url", storage_url, "--json")
    data = json.loads(result.output)
    assert data["status"] == "compensated"
    assert data["failure"]["participant"] == "payments"


def test_other_tenants_and_unknown_ids_are_not_found(storage_url):
    for args in (("ok",), ("missing", "--tenant", "acme")):
        result = _status(*args, "--storage-url", storage_url)
        assert result.exit_code == 1
        assert "No choreographed transaction" in result.output


def test_compensation_failures_are_shown():
    from sagaz.choreography import TransactionStatus
    from sagaz.cli.choreography import _describe

    status = TransactionStatus(
        "t",
        status="failed",
        failure={"participant": "p", "failed_event_type": "e", "reason": "boom"},
        compensated_by={"inventory": {"undone": [], "failed": ["order.created"]}},
    )
    assert "compensation failed for order.created" in "\n".join(_describe(status))
