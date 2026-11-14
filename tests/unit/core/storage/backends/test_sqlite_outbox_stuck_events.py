"""Stuck-event detection and release for ``SQLiteOutboxStorage``.

``claimed_at`` is stored as a Python ISO-8601 string. These tests pin the
claim time explicitly and check it is compared as a point in time, not as
text against SQLite's ``datetime('now')`` format.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sagaz.core.outbox.types import OutboxEvent, OutboxStatus

pytest.importorskip("aiosqlite")

from sagaz.core.storage.backends.sqlite.outbox import SQLiteOutboxStorage  # noqa: E402


@pytest.fixture
async def storage(tmp_path):
    async with SQLiteOutboxStorage(str(tmp_path / "outbox.db")) as storage:
        yield storage


async def _claimed(storage: SQLiteOutboxStorage, count: int = 1) -> list[str]:
    for _ in range(count):
        await storage.insert(OutboxEvent(saga_id="saga-1", event_type="test.event", payload={}))
    claimed = await storage.claim_batch("worker-1", batch_size=count)
    assert len(claimed) == count
    return [event.event_id for event in claimed]


async def _set_claimed_at(storage: SQLiteOutboxStorage, event_id: str, value: str) -> None:
    conn = await storage._get_connection()
    await conn.execute(
        "UPDATE outbox_events SET claimed_at = ? WHERE event_id = ?", (value, event_id)
    )
    await conn.commit()


async def test_claim_older_than_threshold_is_stuck(storage):
    """Regression: same-day ISO ``claimed_at`` never compared below ``datetime('now')``."""
    (event_id,) = await _claimed(storage)
    ten_minutes_ago = datetime.now(UTC) - timedelta(minutes=10)
    await _set_claimed_at(storage, event_id, ten_minutes_ago.isoformat())

    stuck = await storage.get_stuck_events(claimed_older_than_seconds=300)

    assert [event.event_id for event in stuck] == [event_id]


async def test_recent_claim_is_not_stuck(storage):
    await _claimed(storage)

    assert await storage.get_stuck_events(claimed_older_than_seconds=300) == []
    assert await storage.release_stuck_events(claimed_older_than_seconds=300) == 0


async def test_sub_second_threshold(storage):
    (event_id,) = await _claimed(storage)
    await asyncio.sleep(0.3)

    stuck = await storage.get_stuck_events(claimed_older_than_seconds=0.1)

    assert [event.event_id for event in stuck] == [event_id]


async def test_negative_threshold_treats_every_claim_as_stuck(storage):
    ids = await _claimed(storage, 2)

    stuck = await storage.get_stuck_events(claimed_older_than_seconds=-60)

    assert sorted(event.event_id for event in stuck) == sorted(ids)


async def test_utc_offset_is_honoured(storage):
    """02:00+02:00 equals 00:00 UTC, whatever the text says."""
    old_id, recent_id = await _claimed(storage, 2)
    plus_two = timezone(timedelta(hours=2))
    # Ten minutes ago, written in UTC+2: the text looks two hours in the future.
    old = (datetime.now(UTC) - timedelta(minutes=10)).astimezone(plus_two)
    # One minute ago, written in UTC-5: the text looks five hours in the past.
    recent = (datetime.now(UTC) - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=-5)))
    await _set_claimed_at(storage, old_id, old.isoformat())
    await _set_claimed_at(storage, recent_id, recent.isoformat())

    stuck = await storage.get_stuck_events(claimed_older_than_seconds=300)

    assert [event.event_id for event in stuck] == [old_id]


async def test_naive_claimed_at_is_read_as_utc(storage):
    (event_id,) = await _claimed(storage)
    naive_utc = (datetime.now(UTC) - timedelta(minutes=10)).replace(tzinfo=None)
    await _set_claimed_at(storage, event_id, naive_utc.isoformat())

    stuck = await storage.get_stuck_events(claimed_older_than_seconds=300)

    assert [event.event_id for event in stuck] == [event_id]


async def test_release_returns_stuck_claims_to_pending(storage):
    stuck_id, fresh_id = await _claimed(storage, 2)
    await _set_claimed_at(
        storage, stuck_id, (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    )

    released = await storage.release_stuck_events(claimed_older_than_seconds=300)

    assert released == 1
    event = await storage.get_by_id(stuck_id)
    assert event is not None
    assert event.status == OutboxStatus.PENDING
    assert event.claimed_at is None
    assert event.worker_id is None
    fresh = await storage.get_by_id(fresh_id)
    assert fresh is not None
    assert fresh.status == OutboxStatus.CLAIMED
    assert await storage.get_stuck_events(claimed_older_than_seconds=300) == []

    reclaimed = await storage.claim_batch("worker-2", batch_size=10)
    assert [e.event_id for e in reclaimed] == [stuck_id]
