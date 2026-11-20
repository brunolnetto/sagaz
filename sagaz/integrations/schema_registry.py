"""Saga events through a Confluent-compatible schema registry (ADR-014, #502).

:class:`SchemaRegistrySerializer` is an ``EventSerializer`` that encodes events
in Avro or JSON Schema, in Confluent's wire format (magic byte, schema id,
record), through any Confluent-compatible registry: Confluent, Redpanda, or
Apicurio in compatibility mode.

You give the schema of each event type's **payload**. Sagaz wraps it in the
envelope schema, either the outbox message or the choreography ``Event``, so
the envelope's fields are defined once::

    serializer = SchemaRegistrySerializer(
        "http://registry:8081",
        payload_schemas={"order.created": ORDER_CREATED_AVRO},
    )
    broker = create_broker("kafka", bootstrap_servers="...", serializer=serializer)

Subjects follow ``TopicRecordNameStrategy`` (``<topic>-<record name>``), so one
topic can carry several event types. ``deserialize`` decodes registry-encoded and
plain JSON messages alike. Install with ``pip install 'sagaz[schema-registry]'``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from sagaz.core.exceptions import MissingDependencyError

Format = Literal["avro", "json"]
Envelope = Literal["outbox", "choreography"]
MAGIC = b"\x00"

# Envelope fields: (name, Avro type, JSON Schema type, required). The payload
# field ("payload" or "data") takes the event type's schema.
_NULLABLE = (["null", "string"], {"type": ["string", "null"]})
_FIELDS: dict[str, list[tuple[str, Any, Any, bool]]] = {
    "outbox": [
        ("event_id", "string", {"type": "string"}, True),
        ("saga_id", *_NULLABLE, False),
        ("aggregate_type", "string", {"type": "string"}, True),
        ("aggregate_id", *_NULLABLE, False),
        ("event_type", "string", {"type": "string"}, True),
        ("tenant_id", *_NULLABLE, False),
        ("payload", None, None, True),
        ("timestamp", *_NULLABLE, False),
    ],
    "choreography": [
        ("event_type", "string", {"type": "string"}, True),
        ("data", None, None, True),
        ("event_id", "string", {"type": "string"}, True),
        ("saga_id", *_NULLABLE, False),
        ("created_at", "string", {"type": "string"}, True),
        ("tenant_id", *_NULLABLE, False),
        ("causation_id", *_NULLABLE, False),
        ("source", *_NULLABLE, False),
    ],
}


class SchemaError(ValueError):
    """An event type has no schema, or its schema cannot be used."""


def record_name(event_type: str) -> str:
    """The Avro/JSON record name for an event type: ``order.created`` -> ``order_created``."""
    name = re.sub(r"\W", "_", event_type)
    return name if not name[:1].isdigit() else f"_{name}"


def envelope_schema(
    event_type: str,
    payload_schema: str | dict[str, Any],
    *,
    format: Format = "avro",
    envelope: Envelope = "outbox",
) -> str:
    """The full schema of *event_type*'s messages: the envelope around its payload."""
    payload = json.loads(payload_schema) if isinstance(payload_schema, str) else payload_schema
    namespace = f"sagaz.{envelope}"
    name = record_name(event_type)
    if format == "avro":
        return json.dumps(_avro_envelope(event_type, payload, namespace, name, envelope))
    return json.dumps(_json_envelope(payload, f"{namespace}.{name}", envelope))


def _avro_envelope(
    event_type: str, payload: Any, namespace: str, name: str, envelope: Envelope
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("type") != "record":
        msg = f"the Avro payload schema of {event_type!r} must be a record"
        raise SchemaError(msg)
    fields = []
    for field, avro, _, required in _FIELDS[envelope]:
        spec: dict[str, Any] = {"name": field, "type": payload if avro is None else avro}
        if not required:
            spec["default"] = None
        fields.append(spec)
    return {"type": "record", "name": name, "namespace": namespace, "fields": fields}


def _json_envelope(payload: Any, title: str, envelope: Envelope) -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": title,
        "type": "object",
        "properties": {
            field: payload if json_type is None else json_type
            for field, _, json_type, _ in _FIELDS[envelope]
        },
        "required": [field for field, *_, required in _FIELDS[envelope] if required],
    }


def _serde() -> Any:
    try:
        import confluent_kafka.schema_registry as registry
        from confluent_kafka.schema_registry._async import avro, json_schema
        from confluent_kafka.serialization import MessageField, SerializationContext
    except ImportError as exc:
        msg = "confluent-kafka"
        raise MissingDependencyError(msg, "Schema registry serialization") from exc
    return registry, avro, json_schema, MessageField, SerializationContext


def registry_client(registry: Any) -> Any:
    """An ``AsyncSchemaRegistryClient`` from a URL or a config dict (or a client, as is)."""
    if not isinstance(registry, str | dict):
        return registry
    _serde()  # a clear error if confluent-kafka is missing
    from confluent_kafka.schema_registry._async.schema_registry_client import (
        AsyncSchemaRegistryClient,
    )

    return AsyncSchemaRegistryClient({"url": registry} if isinstance(registry, str) else registry)


class SchemaRegistrySerializer:
    """Avro or JSON Schema through a schema registry (an ``EventSerializer``).

    Args:
        registry: The registry URL, a client config dict (``url``, ``basic.auth.user.info``,
            ...), or an ``AsyncSchemaRegistryClient``.
        payload_schemas: Event type -> the schema of its payload (Avro record, or JSON
            Schema), as a dict or JSON text.
        format: ``"avro"`` or ``"json"`` (JSON Schema).
        envelope: ``"outbox"`` for broker messages, ``"choreography"`` for bus events.
        on_missing: For an event type without a schema: ``"error"`` (raise
            :class:`SchemaError`) or ``"json"`` (publish plain JSON).
        auto_register: Register schemas on first use (else they must exist).
    """

    def __init__(
        self,
        registry: Any,
        payload_schemas: dict[str, str | dict[str, Any]],
        *,
        format: Format = "avro",
        envelope: Envelope = "outbox",
        on_missing: Literal["error", "json"] = "error",
        auto_register: bool = True,
    ) -> None:
        self.client = registry_client(registry)
        self.payload_schemas = dict(payload_schemas)
        self.format = format
        self.envelope = envelope
        self.on_missing = on_missing
        self.auto_register = auto_register
        self._serializers: dict[str, Any] = {}
        self._deserializer: Any = None

    def schema(self, event_type: str) -> str:
        """The full (envelope) schema registered for *event_type*."""
        if event_type not in self.payload_schemas:
            msg = f"no schema for event type {event_type!r}"
            raise SchemaError(msg)
        return envelope_schema(
            event_type, self.payload_schemas[event_type], format=self.format, envelope=self.envelope
        )

    async def _serializer(self, event_type: str) -> Any:
        if event_type not in self._serializers:
            registry, avro, json_schema, *_ = _serde()
            conf = {
                "auto.register.schemas": self.auto_register,
                "subject.name.strategy": registry.topic_record_subject_name_strategy,
            }
            schema = self.schema(event_type)
            if self.format == "avro":
                serializer = avro.AsyncAvroSerializer(self.client, schema, conf=conf)
            else:
                serializer = json_schema.AsyncJSONSerializer(schema, self.client, conf=conf)
            self._serializers[event_type] = await _ready(serializer)
        return self._serializers[event_type]

    async def serialize(self, topic: str, record: dict[str, Any], event_type: str) -> bytes:
        if event_type not in self.payload_schemas and self.on_missing == "json":
            return json.dumps(record).encode("utf-8")
        serializer = await self._serializer(event_type)
        *_, message_field, context = _serde()
        data: bytes = await serializer(record, context(topic, message_field.VALUE))
        return data

    async def deserialize(self, topic: str, data: bytes) -> dict[str, Any]:
        if not data.startswith(MAGIC):  # plain JSON (e.g. published before the registry)
            record: dict[str, Any] = json.loads(data.decode("utf-8"))
            return record
        if self._deserializer is None:
            _, avro, json_schema, *_ = _serde()
            deserializer = (
                avro.AsyncAvroDeserializer(self.client)
                if self.format == "avro"
                else json_schema.AsyncJSONDeserializer(None, schema_registry_client=self.client)
            )
            self._deserializer = await _ready(deserializer)
        *_, message_field, context = _serde()
        result: dict[str, Any] = await self._deserializer(data, context(topic, message_field.VALUE))
        return result


async def _ready(serde: Any) -> Any:
    """The async serializers finish initializing when awaited (they may be awaitables)."""
    import inspect

    return await serde if inspect.isawaitable(serde) else serde
