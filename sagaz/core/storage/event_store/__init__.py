"""Event-sourced saga storage (ADR-033, #57).

An event-sourced saga appends every state change to a :class:`SagaEventStore`
instead of only overwriting its current state. Opt in per saga::

    class OrderSaga(Saga):
        class Meta:
            storage_strategy = "event_sourced"
            event_store = "postgresql://..."   # or a SagaEventStore
            snapshot_threshold = 50
"""

from sagaz.core.storage.event_store._base import SagaEventStore, SagaSnapshot
from sagaz.core.storage.event_store._factory import create_event_store
from sagaz.core.storage.event_store.memory import InMemoryEventStore
from sagaz.core.storage.event_store.recorder import (
    DEFAULT_SNAPSHOT_THRESHOLD,
    EVENT_SOURCED,
    SNAPSHOT,
    SagaEventRecorder,
    event_sourcing_settings,
)

__all__ = [
    "DEFAULT_SNAPSHOT_THRESHOLD",
    "EVENT_SOURCED",
    "SNAPSHOT",
    "InMemoryEventStore",
    "SagaEventRecorder",
    "SagaEventStore",
    "SagaSnapshot",
    "create_event_store",
    "event_sourcing_settings",
]
