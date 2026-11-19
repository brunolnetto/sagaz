"""SQLite stores initialize once under concurrent first use.

Each store used to publish its connection before creating its schema (and, for
the saga log, its outbox), so a second coroutine could open another
connection, or write while the DDL held a transaction open ("cannot start a
transaction within a transaction").
"""

from __future__ import annotations

import asyncio

from sagaz.choreography import Event
from sagaz.choreography.state.sqlite import SQLiteParticipantState
from sagaz.core.events import SagaStarted
from sagaz.core.storage.event_store.sqlite import SQLiteEventStore
from sagaz.core.storage.saga_log import LogEvent, LogWrite
from sagaz.core.storage.saga_log._model import EventKind
from sagaz.core.storage.saga_log.sqlite import SQLiteSagaLogStore


async def test_the_saga_log(tmp_path):
    store = SQLiteSagaLogStore(str(tmp_path / "log.db"))
    connects = []
    original = store._init_outbox

    async def counting(conn):
        connects.append(conn)
        await original(conn)

    store._init_outbox = counting  # type: ignore[method-assign]
    try:
        await asyncio.gather(
            *(
                store.write(LogWrite(events=[LogEvent(f"t-{i}", "e", EventKind.BUSINESS)]))
                for i in range(10)
            ),
            *(store.claim_delivery("p", f"e-{i}") for i in range(10)),
        )
        assert len(connects) == 1
        assert len(await store.list_transactions()) == 0
        assert [e.sequence for e in await store.events("t-3")] == [1]
    finally:
        await store.close()


async def test_the_event_store(tmp_path):
    store = SQLiteEventStore(str(tmp_path / "events.db"))
    try:
        await asyncio.gather(*(store.append(SagaStarted(f"s-{i}")) for i in range(10)))
        assert [e.sequence for e in await store.load_stream("s-5")] == [1]
    finally:
        await store.close()


async def test_the_participant_state(tmp_path):
    state = SQLiteParticipantState(str(tmp_path / "state.db"))
    try:
        results = await asyncio.gather(
            *(state.first_delivery("p", f"e-{i % 5}") for i in range(10)),
            *(state.record_action("p", Event("x", saga_id=f"t-{i}")) for i in range(5)),
        )
        assert sum(1 for r in results[:10] if r) == 5
    finally:
        await state.close()
