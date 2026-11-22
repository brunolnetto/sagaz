"""An undone transaction is ``rolled_back`` in both coordination styles (#572)."""

from __future__ import annotations

import pytest

from sagaz.choreography.tracker import (
    OLD_ROLLED_BACK,
    ROLLED_BACK,
    TransactionStatus,
    transaction_status,
)
from sagaz.core.types import SagaStatus


def test_rolled_back_is_the_saga_status_value():
    assert SagaStatus.ROLLED_BACK.value == ROLLED_BACK


@pytest.mark.parametrize(
    ("stored", "read"),
    [("compensated", "rolled_back"), ("rolled_back", "rolled_back"), ("completed", "completed")],
)
def test_the_old_name_is_read_as_rolled_back(stored, read):
    assert transaction_status(stored) == read


def test_a_status_stored_before_2_6_reads_as_rolled_back():
    status = TransactionStatus.from_dict({"correlation_id": "t", "status": OLD_ROLLED_BACK})
    assert status.status == ROLLED_BACK


def test_reports_count_rolled_back_and_keep_the_old_column():
    duckdb = pytest.importorskip("duckdb")
    from sagaz.analytics.queries import SagaQueries

    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE fact_choreography_transaction (flow TEXT, status TEXT, duration_ms DOUBLE,"
        " participant_count INT)"
    )
    conn.execute(
        "INSERT INTO fact_choreography_transaction VALUES"
        " ('order', 'rolled_back', 10, 2), ('order', 'completed', 5, 2)"
    )
    cursor = conn.execute(SagaQueries.CHOREOGRAPHY_SUMMARY)
    names = [d[0] for d in cursor.description]
    (row,) = [dict(zip(names, r, strict=True)) for r in cursor.fetchall()]
    assert row["rolled_back"] == row["compensated"] == 1
    assert row["compensation_rate_pct"] == 50


async def test_the_monitor_lists_rollbacks_stored_under_the_old_name():
    from datetime import UTC, datetime, timedelta

    from sagaz.core.storage.saga_log._model import Coordination, Transaction
    from sagaz.visualization.gradio import _data

    now = datetime.now(UTC)

    def tx(transaction_id: str, status: str, minutes: int) -> Transaction:
        row = Transaction(transaction_id, "order", Coordination.CHOREOGRAPHED, initiator="orders")
        row.status, row.started_at = status, now - timedelta(minutes=minutes)
        return row

    class Log:
        async def list_transactions(self, *, status=None, **_):
            rows = [
                tx("new", "rolled_back", 1),
                tx("old", "compensated", 5),
                tx("ok", "completed", 2),
            ]
            return [r for r in rows if status is None or r.status == status]

    rows = await _data.list_transactions(Log(), status="rolled_back")
    assert [(r["transaction"], r["status"]) for r in rows] == [
        ("new", "rolled_back"),
        ("old", "rolled_back"),
    ]
