"""Debezium on Kafka as a CDC source for the outbox (ADR-011, #50).

Debezium's PostgreSQL connector streams ``saga_outbox`` inserts from the WAL
into a Kafka topic (``<topic.prefix>.public.saga_outbox``);
:class:`DebeziumKafkaSource` consumes that topic and yields the inserted rows as
:class:`~sagaz.integrations.cdc.CDCChange` batches.

Offsets are committed only on :meth:`DebeziumKafkaSource.ack`, so a batch that
was not acknowledged is consumed again after a restart (at least once).
Records that are skipped (updates, deletes, tombstones) or cannot be decoded
are counted in :attr:`DebeziumKafkaSource.stats` and committed with the next
acknowledged batch, so they never stall the stream.

Example::

    source = DebeziumKafkaSource("kafka:9092", topic_prefix="sagaz")
    await source.start()
    async for batch in source.changes():
        for change in batch:
            await publish(change.event)
        await source.ack(batch[-1].position)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from sagaz.integrations.cdc._debezium_envelope import decode_value
from sagaz.integrations.cdc._types import CDCChange, CDCError

logger = logging.getLogger(__name__)

#: Default Debezium ``topic.prefix`` (the shipped connector config uses it).
DEFAULT_TOPIC_PREFIX = "sagaz"

#: Default Kafka consumer group of the CDC worker.
DEFAULT_GROUP_ID = "sagaz-cdc"

#: A Kafka position: the last offset handled per ``TopicPartition``.
Position = Mapping[Any, int]

#: Builds the consumer: ``factory(topic, **config)``, AIOKafkaConsumer-like
#: (``start``, ``stop``, ``getmany``, ``commit``).
ConsumerFactory = Callable[..., Any]


def outbox_topic(prefix: str = DEFAULT_TOPIC_PREFIX, schema: str = "public") -> str:
    """The topic Debezium writes ``saga_outbox`` changes to."""
    return f"{prefix}.{schema}.saga_outbox"


def _aiokafka_consumer(topic: str, **config: Any) -> Any:
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError as exc:  # pragma: no cover - aiokafka ships with sagaz[cdc]
        msg = "DebeziumKafkaSource requires aiokafka: pip install 'sagaz[cdc]'"
        raise CDCError(msg) from exc
    return AIOKafkaConsumer(topic, **config)


def _covers(position: Position, other: Position) -> bool:
    """True if ``position`` is at or past ``other`` on every partition of ``other``."""
    return all(position.get(tp, -1) >= offset for tp, offset in other.items())


@dataclass
class DebeziumStats:
    """Counters of the records a :class:`DebeziumKafkaSource` consumed."""

    received: int = 0
    changes: int = 0
    skipped: int = 0
    failed: int = 0


class DebeziumKafkaSource:
    """Outbox inserts captured by Debezium, consumed from Kafka.

    Args:
        bootstrap_servers: Kafka brokers.
        topic_prefix: The connector's ``topic.prefix``.
        topic: The change topic, overriding ``<topic_prefix>.public.saga_outbox``.
        group_id: Consumer group; its committed offsets are the source position.
        max_batch_size: Most records fetched per batch.
        max_wait_ms: Longest wait for records before a (possibly smaller) batch.
        auto_offset_reset: Where a group without offsets starts (``earliest``
            so changes captured before the first start are not missed).
        consumer_options: Extra ``AIOKafkaConsumer`` arguments, e.g.
            ``security_protocol``, ``sasl_mechanism``, ``ssl_context``.
        consumer_factory: Builds the consumer (tests inject a fake).
    """

    name = "debezium"

    def __init__(
        self,
        bootstrap_servers: str | list[str] = "localhost:9092",
        *,
        topic_prefix: str = DEFAULT_TOPIC_PREFIX,
        topic: str | None = None,
        group_id: str = DEFAULT_GROUP_ID,
        max_batch_size: int = 100,
        max_wait_ms: int = 500,
        auto_offset_reset: str = "earliest",
        consumer_options: Mapping[str, Any] | None = None,
        consumer_factory: ConsumerFactory | None = None,
    ) -> None:
        if max_batch_size < 1:
            msg = "max_batch_size must be at least 1"
            raise ValueError(msg)
        if max_wait_ms < 0:
            msg = "max_wait_ms must not be negative"
            raise ValueError(msg)
        self.topic = topic or outbox_topic(topic_prefix)
        self.group_id = group_id
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms
        self.stats = DebeziumStats()
        self._config: dict[str, Any] = {
            "bootstrap_servers": bootstrap_servers,
            "group_id": group_id,
            "auto_offset_reset": auto_offset_reset,
            **(consumer_options or {}),
            "enable_auto_commit": False,  # offsets move only on ack()
        }
        self._factory = consumer_factory or _aiokafka_consumer
        self._consumer: Any = None
        self._running = False
        self._seen: dict[Any, int] = {}
        self._outstanding: Position | None = None

    @property
    def consumer_config(self) -> dict[str, Any]:
        """The arguments the consumer is built with (besides the topic)."""
        return dict(self._config)

    async def start(self) -> None:
        """Connect the consumer and join the group (idempotent)."""
        if self._consumer is not None:
            return
        consumer = self._factory(self.topic, **self._config)
        try:
            await consumer.start()
        except Exception as exc:
            msg = f"cannot start the Kafka consumer for {self.topic!r}: {exc}"
            raise CDCError(msg) from exc
        self._consumer = consumer
        self._running = True
        self._seen.clear()
        self._outstanding = None

    async def stop(self) -> None:
        """Leave the group; unacknowledged changes are redelivered on the next start."""
        self._running = False
        consumer, self._consumer = self._consumer, None
        if consumer is not None:
            await consumer.stop()

    async def changes(self) -> AsyncIterator[list[CDCChange]]:
        """Batches of captured inserts, until :meth:`stop` is called."""
        consumer = self._require_consumer()
        while self._running:
            records = await self._poll(consumer)
            batch = self._decode_batch(records)
            if batch:
                self._outstanding = batch[-1].position
                yield batch
            elif records and self._outstanding is None:
                # Only skipped records and nothing pending: move past them now.
                await self.ack(dict(self._seen))

    async def ack(self, position: Any) -> None:
        """Commit the offsets after ``position`` (a change's position) for its partitions."""
        if not position:
            return
        consumer = self._require_consumer()
        try:
            await consumer.commit({tp: offset + 1 for tp, offset in position.items()})
        except Exception as exc:
            msg = f"cannot commit offsets for {self.topic!r}: {exc}"
            raise CDCError(msg) from exc
        if self._outstanding is not None and _covers(position, self._outstanding):
            self._outstanding = None

    def _require_consumer(self) -> Any:
        if self._consumer is None:
            msg = "DebeziumKafkaSource is not started"
            raise CDCError(msg)
        return self._consumer

    async def _poll(self, consumer: Any) -> dict[Any, list[Any]]:
        try:
            records: dict[Any, list[Any]] = await consumer.getmany(
                timeout_ms=self.max_wait_ms, max_records=self.max_batch_size
            )
        except Exception as exc:
            if not self._running:  # stop() closed the consumer mid-poll
                return {}
            msg = f"cannot consume {self.topic!r}: {exc}"
            raise CDCError(msg) from exc
        return records

    def _decode_batch(self, records: Mapping[Any, list[Any]]) -> list[CDCChange]:
        changes: list[CDCChange] = []
        for tp, messages in records.items():
            for message in messages:
                self._seen[tp] = message.offset
                decoded = self._decode(tp, message)
                if decoded is not None:
                    event, committed_at = decoded
                    changes.append(CDCChange(event, committed_at, dict(self._seen)))
        if changes:
            # Acknowledging the batch also commits the skipped records after its last change.
            changes[-1] = replace(changes[-1], position=dict(self._seen))
        return changes

    def _decode(self, tp: Any, message: Any) -> Any:
        self.stats.received += 1
        try:
            decoded = decode_value(message.value)
        except CDCError as exc:
            self.stats.failed += 1
            logger.warning(
                "Skipping undecodable Debezium record %s@%s: %s", tp, message.offset, exc
            )
            return None
        if decoded is None:
            self.stats.skipped += 1
        else:
            self.stats.changes += 1
        return decoded
