"""How published events become bytes (ADR-014).

An :class:`EventSerializer` turns an event's record (the outbox envelope, or a
choreography event's ``to_dict()``) into a message value, and back. The default
is JSON, as sagaz always published. ``sagaz.integrations.schema_registry``
provides Avro and JSON Schema through a schema registry.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventSerializer(Protocol):
    """Encodes and decodes published event records."""

    async def serialize(self, topic: str, record: dict[str, Any], event_type: str) -> bytes:
        """The message value for *record*, an event of *event_type* on *topic*."""
        ...

    async def deserialize(self, topic: str, data: bytes) -> dict[str, Any]:
        """The record a message value on *topic* carries."""
        ...


class JsonEventSerializer:
    """UTF-8 JSON: sagaz's format without a schema registry."""

    async def serialize(self, topic: str, record: dict[str, Any], event_type: str) -> bytes:
        return json.dumps(record).encode("utf-8")

    async def deserialize(self, topic: str, data: bytes) -> dict[str, Any]:
        record: dict[str, Any] = json.loads(data.decode("utf-8"))
        return record
