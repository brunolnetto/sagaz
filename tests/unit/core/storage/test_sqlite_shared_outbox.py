"""The SQLite saga log's outbox shares the log's connection and lock (#500)."""

from __future__ import annotations

import asyncio

from sagaz.choreography import EventBus
from sagaz.choreography.relay import ChoreographyRelay
from sagaz.core.outbox.types import OutboxStatus
from sagaz.core.storage.saga_log import EventKind, LogEvent, LogWrite, OutboxMessage
from sagaz.core.storage.saga_log._sqlite_outbox import SharedSQLiteOutboxStorage
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore


def publish(tid: str) -> LogWrite:
    event = LogEvent(tid, "order.created", EventKind.BUSINESS)
    return LogWrite(
        events=[event],
        publish=[OutboxMessage(tid, "order.created", {"n": 1}, log_event_id=event.event_id)],
    )


async def test_an_in_memory_log_has_an_outbox():
    async with SQLiteSagaLogStore(":memory:") as log:
        outbox = log.outbox_storage()
        assert isinstance(outbox, SharedSQLiteOutboxStorage)
        await log.write(publish("t-1"))
        (claimed,) = await outbox.claim_batch("worker", batch_size=10)
        assert claimed.saga_id == "t-1"
        # update_status reads get_by_id: nested calls must not deadlock on the lock.
        await asyncio.wait_for(outbox.update_status(claimed.event_id, OutboxStatus.SENT), 5)
        assert (await outbox.get_by_id(claimed.event_id)).status == OutboxStatus.SENT
        await outbox.close()  # the store's connection stays open
        assert await outbox.get_pending_count() == 0


async def test_concurrent_writes_and_claims_take_turns(tmp_path):
    async with SQLiteSagaLogStore(str(tmp_path / "log.db")) as log:
        outbox = log.outbox_storage()

        async def claim_all() -> int:
            claimed = 0
            for _ in range(20):
                batch = await outbox.claim_batch("worker", batch_size=5)
                for event in batch:
                    await outbox.update_status(event.event_id, OutboxStatus.SENT)
                claimed += len(batch)
                await asyncio.sleep(0)
            return claimed

        results = await asyncio.gather(
            *(log.write(publish(f"t-{i}")) for i in range(50)), claim_all(), claim_all()
        )
        drained = await claim_all()
        assert sum(results[-2:]) + drained == 50
        assert await outbox.get_pending_count() == 0


def test_a_log_outbox_relays_whole_batches(tmp_path):
    log = SQLiteSagaLogStore(str(tmp_path / "log.db"))
    relay = ChoreographyRelay(log.outbox_storage(), EventBus())
    assert relay.worker.config.batch_size == 100
