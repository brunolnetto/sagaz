"""Build an event store from a URL."""

from __future__ import annotations

from sagaz.core.storage.event_store._base import SagaEventStore


def create_event_store(url: str) -> SagaEventStore:
    """An event store for ``url``.

    Supported: ``memory://``, ``sqlite://<path>`` (``sqlite://:memory:`` too)
    and ``postgresql://...`` (or ``postgres://...``).
    """
    if url.startswith("memory://"):
        from sagaz.core.storage.event_store.memory import InMemoryEventStore

        return InMemoryEventStore()
    if url.startswith("sqlite://"):
        from sagaz.core.storage.event_store.sqlite import SQLiteEventStore

        return SQLiteEventStore(url[len("sqlite://") :] or ":memory:")
    if url.startswith(("postgresql://", "postgres://")):
        from sagaz.core.storage.event_store.postgresql import PostgreSQLEventStore

        return PostgreSQLEventStore(url)
    msg = f"Unsupported event store URL {url!r}: use memory://, sqlite:// or postgresql://"
    raise ValueError(msg)
