"""``sagaz schema``: event schemas in a schema registry (ADR-014, #502).

You write the schema of an event type's payload; these commands wrap it in the
envelope sagaz publishes (outbox message or choreography event) and work with
the subject the serializer uses (``<topic>-sagaz.<envelope>.<record name>``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import click

_FORMAT = click.option(
    "--format", "fmt", type=click.Choice(["avro", "json"]), default="avro", show_default=True
)
_ENVELOPE = click.option(
    "--envelope",
    type=click.Choice(["outbox", "choreography"]),
    default="outbox",
    show_default=True,
    help="outbox: broker messages; choreography: events on the Kafka bus.",
)
_PAYLOAD = click.option(
    "--payload-schema",
    "payload_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="The schema of the event type's payload (Avro record or JSON Schema), as JSON.",
)
_REGISTRY = click.option(
    "--registry",
    envvar="SAGAZ_SCHEMA_REGISTRY_URL",
    required=True,
    help="Schema registry URL (or SAGAZ_SCHEMA_REGISTRY_URL).",
)
_TOPIC = click.option(
    "--topic",
    default=None,
    help="The topic (default: the event type for outbox, sagaz.choreography for the bus).",
)


@click.group("schema")
def schema_cli() -> None:
    """Event schemas in a schema registry (Avro, JSON Schema)."""


def _full_schema(event_type: str, payload_file: Path, fmt: str, envelope: str) -> str:
    from sagaz.integrations.schema_registry import SchemaError, envelope_schema

    try:
        return envelope_schema(
            event_type,
            json.loads(payload_file.read_text()),
            format=fmt,  # type: ignore[arg-type]
            envelope=envelope,  # type: ignore[arg-type]
        )
    except (SchemaError, ValueError) as exc:
        raise click.BadParameter(str(exc), param_hint="--payload-schema") from exc


def _subject(event_type: str, envelope: str, topic: str | None) -> str:
    from sagaz.integrations.schema_registry import record_name

    topic = topic or (event_type if envelope == "outbox" else "sagaz.choreography")
    return f"{topic}-sagaz.{envelope}.{record_name(event_type)}"


def _schema(schema_str: str, fmt: str) -> Any:
    from confluent_kafka.schema_registry import Schema

    return Schema(schema_str, "AVRO" if fmt == "avro" else "JSON")


@schema_cli.command("envelope")
@click.argument("event_type")
@_PAYLOAD
@_FORMAT
@_ENVELOPE
def envelope_cmd(event_type: str, payload_file: Path, fmt: str, envelope: str) -> None:
    """Print the full schema of EVENT_TYPE's messages: the envelope around its payload."""
    schema = json.loads(_full_schema(event_type, payload_file, fmt, envelope))
    click.echo(json.dumps(schema, indent=2))


@schema_cli.command("check")
@click.argument("event_type")
@_PAYLOAD
@_REGISTRY
@_FORMAT
@_ENVELOPE
@_TOPIC
def check_cmd(
    event_type: str, payload_file: Path, registry: str, fmt: str, envelope: str, topic: str | None
) -> None:
    """Check EVENT_TYPE's schema against the versions registered for its subject."""
    from sagaz.integrations.schema_registry import registry_client

    schema = _schema(_full_schema(event_type, payload_file, fmt, envelope), fmt)
    subject = _subject(event_type, envelope, topic)

    async def check() -> bool | None:
        client = registry_client(registry)
        subjects = await client.get_subjects()
        if subject not in subjects:
            return None
        result: bool = await client.test_compatibility(subject, schema)
        return result

    compatible = asyncio.run(check())
    if compatible is None:
        click.echo(f"{subject}: not registered yet (any schema is accepted)")
    elif compatible:
        click.echo(f"{subject}: compatible")
    else:
        click.echo(f"{subject}: NOT compatible with the registered versions")
        raise SystemExit(1)


@schema_cli.command("register")
@click.argument("event_type")
@_PAYLOAD
@_REGISTRY
@_FORMAT
@_ENVELOPE
@_TOPIC
def register_cmd(
    event_type: str, payload_file: Path, registry: str, fmt: str, envelope: str, topic: str | None
) -> None:
    """Register EVENT_TYPE's schema under its subject; print the schema id."""
    from sagaz.integrations.schema_registry import registry_client

    schema = _schema(_full_schema(event_type, payload_file, fmt, envelope), fmt)
    subject = _subject(event_type, envelope, topic)

    async def register() -> int:
        schema_id: int = await registry_client(registry).register_schema(subject, schema)
        return schema_id

    click.echo(f"{subject}: schema id {asyncio.run(register())}")
