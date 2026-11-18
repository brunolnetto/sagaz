"""In-memory event store, for tests and single-process development."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

from sagaz.core.events import SagaEvent
from sagaz.core.storage._tenancy import scoped_tenant, write_tenant
from sagaz.core.storage.event_store._base import SagaEventStore, SagaSnapshot


class InMemoryEventStore(SagaEventStore):
    """Keeps streams in process memory, serialized as the persistent stores do."""

    def __init__(self) -> None:
        self._streams: dict[tuple[str, str], list[str]] = {}
        self._snapshots: dict[tuple[str, str], dict[int, SagaSnapshot]] = {}
        self._lock = asyncio.Lock()

    async def append(self, event: SagaEvent) -> SagaEvent:
        tenant = write_tenant(event.tenant_id)
        async with self._lock:
            stream = self._streams.setdefault((tenant, event.saga_id), [])
            stored = replace(event, tenant_id=tenant, sequence=len(stream) + 1)
            stream.append(json.dumps(stored.to_dict()))
        return stored

    def _keys(self, saga_id: str, table: dict) -> list[tuple[str, str]]:
        tenant = scoped_tenant()
        return sorted(k for k in table if k[1] == saga_id and tenant in (None, k[0]))

    async def load_stream(self, saga_id: str) -> list[SagaEvent]:
        return await self.load_stream_after(saga_id, 0)

    async def load_stream_after(self, saga_id: str, after_sequence: int) -> list[SagaEvent]:
        return [
            event
            for key in self._keys(saga_id, self._streams)
            for event in map(SagaEvent.from_dict, map(json.loads, self._streams[key]))
            if event.sequence > after_sequence
        ]

    async def save_snapshot(self, snapshot: SagaSnapshot) -> None:
        tenant = write_tenant(snapshot.tenant_id)
        stored = replace(snapshot, tenant_id=tenant, state=json.loads(json.dumps(snapshot.state)))
        self._snapshots.setdefault((tenant, snapshot.saga_id), {})[snapshot.sequence] = stored

    async def load_latest_snapshot(self, saga_id: str) -> SagaSnapshot | None:
        snapshots = [
            snapshot
            for key in self._keys(saga_id, self._snapshots)
            for snapshot in self._snapshots[key].values()
        ]
        return max(snapshots, key=lambda s: s.sequence, default=None)
