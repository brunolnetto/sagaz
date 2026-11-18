"""Records a saga run's events (ADR-033, #57).

The execution engine creates one :class:`SagaEventRecorder` per run of an
event-sourced saga and hands it each lifecycle event. The recorder appends
the event, keeps the run's projection current and, every
``snapshot_threshold`` events, saves that projection as a snapshot.

Recording never fails a saga: like the snapshot storage writes, an append that
fails is logged and counted (``outcome="error"``), and the saga goes on.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any

from sagaz.core.events import SagaEvent
from sagaz.core.storage._tenancy import write_tenant
from sagaz.core.storage.event_store._base import SagaEventStore, SagaSnapshot
from sagaz.projections.summary import SagaSummaryProjection, load_projection

logger = logging.getLogger(__name__)

#: The default and the opt-in values of ``Meta.storage_strategy``.
SNAPSHOT, EVENT_SOURCED = "snapshot", "event_sourced"
DEFAULT_SNAPSHOT_THRESHOLD = 50

try:
    from prometheus_client import Counter

    EVENT_STORE_EVENTS: Any = Counter(
        "sagaz_event_store_events_total",
        "Saga events appended to the event store",
        ["saga_name", "event_type", "outcome"],
    )
    EVENT_STORE_SNAPSHOTS: Any = Counter(
        "sagaz_event_store_snapshots_total",
        "Snapshots of saga projections written to the event store",
        ["saga_name", "outcome"],
    )
except ImportError:  # pragma: no cover - prometheus_client is optional
    EVENT_STORE_EVENTS = EVENT_STORE_SNAPSHOTS = None


def _count(counter: Any, **labels: str) -> None:
    if counter is not None:
        counter.labels(**labels).inc()


class SagaEventRecorder:
    """Appends one saga run's events and snapshots its projection."""

    def __init__(
        self,
        store: SagaEventStore,
        saga_id: str,
        saga_name: str,
        snapshot_threshold: int = DEFAULT_SNAPSHOT_THRESHOLD,
    ) -> None:
        if snapshot_threshold < 1:
            msg = f"snapshot_threshold must be at least 1, got {snapshot_threshold}"
            raise ValueError(msg)
        self.store = store
        self.saga_id = saga_id
        self.saga_name = saga_name
        self.snapshot_threshold = snapshot_threshold
        self.tenant_id = write_tenant()
        self.projection = SagaSummaryProjection(saga_id)
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        """Load the saga's existing state, so a re-run continues its stream."""
        await self._reload()

    async def _reload(self) -> bool:
        try:
            existing = await load_projection(self.store, self.saga_id)
        except Exception as error:
            logger.warning(f"Could not load the event stream of saga {self.saga_id}: {error}")
            return False
        self.projection = existing or SagaSummaryProjection(self.saga_id)
        return True

    async def record(self, event: SagaEvent) -> SagaEvent | None:
        """Append ``event`` (stamped with this run's saga and tenant).

        Returns the stored event, or ``None`` when the append failed.
        """
        event = replace(
            event, saga_id=self.saga_id, saga_name=self.saga_name, tenant_id=self.tenant_id
        )
        async with self._lock:
            try:
                stored = await self.store.append(event)
            except Exception as error:
                logger.warning(
                    f"Could not record {event.event_type} for saga {self.saga_id}: {error}"
                )
                _count(
                    EVENT_STORE_EVENTS,
                    saga_name=self.saga_name,
                    event_type=event.event_type,
                    outcome="error",
                )
                return None
            _count(
                EVENT_STORE_EVENTS,
                saga_name=self.saga_name,
                event_type=event.event_type,
                outcome="appended",
            )
            await self._project(stored)
        return stored

    async def _project(self, stored: SagaEvent) -> None:
        before = self.projection.last_sequence
        # Another writer (or a failed load) left a gap: rebuild from the store.
        if stored.sequence != before + 1 and not await self._reload():
            return
        self.projection.apply(stored)
        # Snapshot whenever the stream crosses a multiple of the threshold.
        threshold = self.snapshot_threshold
        if self.projection.last_sequence // threshold > before // threshold:
            await self._snapshot()

    async def _snapshot(self) -> None:
        snapshot = SagaSnapshot(
            self.saga_id,
            self.projection.last_sequence,
            self.projection.to_dict(),
            self.tenant_id,
        )
        try:
            await self.store.save_snapshot(snapshot)
        except Exception as error:
            logger.warning(f"Could not snapshot saga {self.saga_id}: {error}")
            _count(EVENT_STORE_SNAPSHOTS, saga_name=self.saga_name, outcome="error")
            return
        _count(EVENT_STORE_SNAPSHOTS, saga_name=self.saga_name, outcome="saved")


_stores_by_url: dict[str, SagaEventStore] = {}


def _as_store(value: SagaEventStore | str) -> SagaEventStore:
    if isinstance(value, str):
        from sagaz.core.storage.event_store._factory import create_event_store

        if value not in _stores_by_url:
            _stores_by_url[value] = create_event_store(value)
        return _stores_by_url[value]
    return value


def event_sourcing_settings(saga: Any) -> tuple[SagaEventStore, int] | None:
    """The event store and snapshot threshold of ``saga``, or ``None`` if not event-sourced.

    Read from the saga class's ``Meta`` (``storage_strategy``, ``event_store``,
    ``snapshot_threshold``), falling back to the saga's ``SagaConfig``.
    ``event_store`` may be a store or a URL.
    """
    meta = getattr(type(saga), "Meta", None)
    config = getattr(saga, "_config", None)

    def setting(name: str, default: Any = None) -> Any:
        value = getattr(meta, name, None)
        return value if value is not None else getattr(config, name, default)

    strategy = setting("storage_strategy", SNAPSHOT)
    # Duck-typed configs (or mocks) without the setting keep the default.
    if not isinstance(strategy, str) or strategy == SNAPSHOT:
        return None
    if strategy != EVENT_SOURCED:
        msg = f"storage_strategy must be {SNAPSHOT!r} or {EVENT_SOURCED!r}, got {strategy!r}"
        raise ValueError(msg)
    store = setting("event_store")
    if store is None:
        msg = (
            "storage_strategy='event_sourced' needs an event store: set Meta.event_store "
            "or SagaConfig.event_store (a SagaEventStore or a URL)"
        )
        raise ValueError(msg)
    return _as_store(store), int(setting("snapshot_threshold", DEFAULT_SNAPSHOT_THRESHOLD))
