"""Export the unified saga log to Apache Fluss (ADR-013, #481).

:class:`FlussSink` writes committed log events to a Fluss primary-key table on
``(dt, tenant_id, transaction_id, sequence)``: the log's own key, plus the day
partition. An event written twice (the exporter delivers at least once) is an
upsert of the same values, so the table holds each event exactly once. With
the datalake enabled on the table, Fluss's tiering service moves it to
Iceberg::

    async with create_saga_log_store(url) as log:
        exporter = SagaLogExporter(SagaLogReader(log, "fluss"), FlussSink("fluss:9123"))
        await exporter.start()

It uses the official async client (``pip install 'sagaz[fluss]'``, module
``fluss``), so no network call blocks the event loop.
"""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sagaz.core.exceptions import MissingDependencyError

if TYPE_CHECKING:
    from sagaz.core.storage.saga_log import ExportedEvent

#: Column name and Arrow type name of the Fluss table, in order.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("tenant_id", "string"),
    ("transaction_id", "string"),
    ("sequence", "int64"),
    ("event_id", "string"),
    ("event_type", "string"),
    ("kind", "string"),
    ("coordination", "string"),
    ("flow", "string"),
    ("source", "string"),
    ("causation_id", "string"),
    ("payload", "string"),
    ("occurred_at", "timestamp"),
    ("occurred_at_ms", "int64"),  # epoch milliseconds: Flink SQL cannot do millisecond math
    ("event_version", "int32"),
    ("dt", "string"),
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
PRIMARY_KEY = ("dt", "tenant_id", "transaction_id", "sequence")
PARTITION_KEY = "dt"
# A transaction's events stay in one bucket, in order. Tiering to Iceberg takes
# at most one bucket key.
BUCKET_KEYS = ("transaction_id",)
NOT_NULL = frozenset(
    {"tenant_id", "transaction_id", "sequence", "event_id", "event_type", "kind"}
    | {"occurred_at", "occurred_at_ms", "event_version", "dt"}
)


def table_properties(*, datalake: bool = True, freshness: str | None = None) -> dict[str, str]:
    """Tiered to the lake when *datalake*, at most *freshness* behind (Fluss's default: 3min).

    Day partitions are created by the sink as events arrive, not by Fluss's
    auto-partitioning: its retention drops old partitions, so a backfill of
    older events could be dropped before it is tiered.
    """
    properties: dict[str, str] = {}
    if datalake:
        properties["table.datalake.enabled"] = "true"
        if freshness:
            properties["table.datalake.freshness"] = freshness
    return properties


def fluss_row(exported: ExportedEvent) -> dict[str, Any]:
    """A log event as a row of the Fluss table."""
    event = exported.event
    occurred_at = event.occurred_at.astimezone(UTC)
    return {
        "tenant_id": event.tenant_id,
        "transaction_id": event.transaction_id,
        "sequence": event.sequence,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "kind": str(event.kind),
        "coordination": exported.coordination,
        "flow": exported.flow,
        "source": event.source,
        "causation_id": event.causation_id,
        "payload": json.dumps(event.payload, sort_keys=True, default=str),
        "occurred_at": occurred_at,
        "occurred_at_ms": (occurred_at - _EPOCH) // timedelta(milliseconds=1),  # exact
        "event_version": event.event_version,
        "dt": occurred_at.strftime("%Y-%m-%d"),
    }


def fluss_ddl(table: str = "sagaz.saga_log_event", *, datalake: bool = True) -> str:
    """The Flink SQL ``CREATE TABLE`` of the Fluss table, for catalogs managed by hand.

    Identifiers are quoted, so no column name can clash with a Flink SQL keyword.
    """
    sql_types = {
        "string": "STRING",
        "int64": "BIGINT",
        "int32": "INT",
        "timestamp": "TIMESTAMP_LTZ(6)",
    }
    columns = ",\n".join(
        f"    {'`' + name + '`':<17} {sql_types[kind]}{' NOT NULL' if name in NOT_NULL else ''}"
        for name, kind in COLUMNS
    )
    options = {"bucket.key": ",".join(BUCKET_KEYS), **table_properties(datalake=datalake)}
    with_clause = ",\n".join(f"    '{k}' = '{v}'" for k, v in options.items())
    return (
        f"CREATE TABLE IF NOT EXISTS {table} (\n{columns},\n"
        f"    PRIMARY KEY ({', '.join(f'`{k}`' for k in PRIMARY_KEY)}) NOT ENFORCED\n"
        f") PARTITIONED BY (`{PARTITION_KEY}`) WITH (\n{with_clause}\n);"
    )


def _arrow_schema() -> Any:
    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover - installed with the extra
        msg = "pyarrow"
        raise MissingDependencyError(msg, "Fluss export") from exc
    types = {
        "string": pa.string(),
        "int64": pa.int64(),
        "int32": pa.int32(),
        "timestamp": pa.timestamp("us", tz="UTC"),
    }
    return pa.schema(
        [pa.field(name, types[kind], nullable=name not in NOT_NULL) for name, kind in COLUMNS]
    )


class FlussSink:
    """Writes saga log events to a Fluss primary-key table (an ``ExportSink``).

    Args:
        bootstrap_servers: The Fluss coordinator(s), ``host:port[,host:port]``.
        table: ``database.table``; created if missing when *create_table*.
        create_table: Create the database and table on first use.
        datalake: Enable tiering to the lake (Iceberg) on a created table.
        freshness: How far behind the lake may be, e.g. ``"1min"`` (created table).
        properties: Extra client configuration (``Config`` properties).
        client: The client module; ``fluss`` by default (tests pass a fake).
    """

    def __init__(
        self,
        bootstrap_servers: str,
        table: str = "sagaz.saga_log_event",
        *,
        create_table: bool = True,
        datalake: bool = True,
        freshness: str | None = None,
        properties: dict[str, str] | None = None,
        client: Any = None,
    ) -> None:
        database, _, name = table.partition(".")
        if not database or not name:
            msg = f"Fluss table must be 'database.table', got {table!r}"
            raise ValueError(msg)
        self.bootstrap_servers = bootstrap_servers
        self.database = database
        self.table_name = name
        self.create_table = create_table
        self.datalake = datalake
        self.freshness = freshness
        self.properties = dict(properties or {})
        self._client = client
        self._connection: Any = None
        self._admin: Any = None
        self._path: Any = None
        self._writer: Any = None
        self._partitions: set[str] = set()  # created (or found) in this session

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                self._client = importlib.import_module("fluss")
            except ImportError as exc:
                msg = "pyfluss"
                raise MissingDependencyError(msg, "Fluss export") from exc
        return self._client

    async def _ensure_writer(self) -> Any:
        if self._writer is None:
            fluss = self.client
            config = fluss.Config({"bootstrap.servers": self.bootstrap_servers, **self.properties})
            connection = await fluss.FlussConnection.create(config)
            try:
                path = fluss.TablePath(self.database, self.table_name)
                admin = connection.get_admin()
                if self.create_table:
                    await self._create(fluss, admin, path)
                table = await connection.get_table(path)
                self._writer = table.new_upsert().create_writer()
                self._admin, self._path = admin, path
            except BaseException:
                await connection.close()
                raise
            self._connection = connection
        return self._writer

    async def _create(self, fluss: Any, admin: Any, path: Any) -> None:
        await admin.create_database(self.database, ignore_if_exists=True)
        descriptor = fluss.TableDescriptor(
            fluss.Schema(_arrow_schema(), primary_keys=list(PRIMARY_KEY)),
            partition_keys=[PARTITION_KEY],
            bucket_keys=list(BUCKET_KEYS),
            properties=table_properties(datalake=self.datalake, freshness=self.freshness),
        )
        await admin.create_table(path, descriptor, ignore_if_exists=True)

    async def write(self, events: list[ExportedEvent]) -> None:
        """Upsert *events*; return once Fluss acknowledged every one."""
        if not events:
            return
        writer = await self._ensure_writer()
        rows = [fluss_row(e) for e in events]
        try:
            for day in sorted({row[PARTITION_KEY] for row in rows} - self._partitions):
                await self._admin.create_partition(
                    self._path, {PARTITION_KEY: day}, ignore_if_exists=True
                )
                self._partitions.add(day)
            handles = [writer.upsert(row) for row in rows]
            await writer.flush()
            for handle in handles:
                await handle.wait()
        except BaseException:
            # A writer that failed may hold a broken session: reconnect next time.
            await self.close()
            raise

    async def close(self) -> None:
        connection, self._connection, self._writer = self._connection, None, None
        self._admin = self._path = None
        self._partitions.clear()
        if connection is not None:
            await connection.close()
