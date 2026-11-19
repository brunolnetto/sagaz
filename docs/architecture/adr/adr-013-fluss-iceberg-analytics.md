# ADR-013: Fluss + Iceberg Analytics on the Unified Saga Log

## Status

**Accepted** | Date: 2026-11-19 | Target: v2.2.0 (Wave 7, milestone #18)

Revised on 2026-11-19 to build on ADR-041. The first version (2024-12-27) fed
Fluss from an in-process listener. That design predates the unified saga log,
and its prototype (PR #67) is superseded: see "Revision notes".

## Dependencies

- **ADR-041, unified saga log (v2.1.0)**: the only input. Everything analytics
  needs is in `saga_log_event`, for orchestrated and choreographed sagas alike.
- **ADR-011, CDC**: `PgLogicalSource` streams a table's inserts from the WAL.
- **ADR-036, embedded analytics**: the DuckDB pipeline reads the same log; its
  Gold queries are the reference the Flink SQL versions must match.

## Context

The embedded pipeline (ADR-036) answers analytics questions from one process
and over a bounded window. Teams running many services need:

- **Real-time views** across every service writing the log: throughput,
  compensation rate and latency per flow, within seconds.
- **History** kept cheaply and queryable by standard engines (Trino, Spark,
  DuckDB) for months: trends, post-mortems and compliance.

ADR-041 gives this a single, typed, append-only, tenant-aware stream. The
remaining questions are how to move it out of the OLTP database without losing
events, and where to keep it.

## Decision

Export `saga_log_event` to an **Apache Fluss** primary-key table, and let
Fluss's own **tiering service** move it to **Apache Iceberg**.

```
 services ──▶ saga_log_event ──▶ exporter ──▶ Fluss PK table ──▶ tiering ──▶ Iceberg
 (OLTP, ADR-041)  (CDC or cursor)  (at least once)  (idempotent)   (Flink job)  (history)
                                                        │                           │
                                               Flink SQL (streaming)       Flink SQL (batch)
```

### 1. The source is the log, read durably

There is no in-process listener and no in-memory buffer. An exporter reads
committed rows of `saga_log_event` and acknowledges its position only after
the sink has accepted them, so a crash or a Fluss outage delays events and
never drops them.

Two readers share one interface:

- **CDC (PostgreSQL)**: `PgLogicalSource(table="saga_log_event")` streams
  inserts in commit order. It is the low-latency path.
- **Cursor polling (PostgreSQL and SQLite)**: it needs an order that a poller
  cannot skip past.
  - **SQLite** has a single writer, so an `INTEGER PRIMARY KEY` rowid is
    assigned in commit order.
  - **PostgreSQL**: a sequence is not commit-ordered, since a transaction that
    commits later can hold a lower value. Each row therefore records its
    writing transaction (`xid8 DEFAULT pg_current_xact_id()`), and the poller
    reads only rows whose transaction is older than every transaction still in
    flight (`pg_snapshot_xmin(pg_current_snapshot())`). This is the standard
    technique for ordered outbox polling.
  - **Cursor table**: the poller's position is kept in a `saga_export_cursor`
    table, one row per exporter name, in the log's database.

### 2. The sink is idempotent, so at least once is enough

The Fluss table is a primary-key table on `(tenant_id, transaction_id,
sequence)`, the same key as `saga_log_event`. A redelivered row is an upsert of
identical values, so the reader's at-least-once delivery becomes an
exactly-once table. The exporter writes through the official Python client
(`pyfluss`, RPC to the bootstrap servers), never through a hand-written HTTP
call.

### 3. Iceberg comes from Fluss, not from sagaz

Fluss tiers tables that have the datalake enabled to Iceberg with its tiering
service, a Flink job that Fluss coordinates with exactly-once semantics. Sagaz
ships its configuration (catalog, warehouse, jobs) and no Python Iceberg
writer. History is queried from the Iceberg catalog, and fresh rows from the
Fluss stream. Fluss 1.0 cannot read a primary-key table in batch as a union of
both with Iceberg (`lake records must instance of sorted view`).

### Table

The options are checked against the pinned Fluss version when it is
implemented.

```sql
CREATE TABLE sagaz.saga_log_event (
    tenant_id       STRING NOT NULL,
    transaction_id  STRING NOT NULL,
    sequence        BIGINT NOT NULL,
    event_id        STRING NOT NULL,
    event_type      STRING NOT NULL,
    kind            STRING NOT NULL,   -- lifecycle | business | compensate | compensated
    coordination    STRING,            -- orchestrated | choreographed (from saga_transaction)
    flow            STRING,
    source          STRING,
    causation_id    STRING,
    payload         STRING,            -- JSON
    occurred_at     TIMESTAMP_LTZ(6) NOT NULL,
    event_version   INT NOT NULL,
    dt              STRING NOT NULL,   -- day of occurred_at, the partition
    PRIMARY KEY (dt, tenant_id, transaction_id, sequence) NOT ENFORCED
) PARTITIONED BY (dt) WITH (
    'bucket.key' = 'transaction_id',          -- Iceberg tiering takes one bucket key
    'table.datalake.enabled' = 'true'
);
```

- **Denormalized columns:** `coordination` and `flow` are copied from the
  transaction, so the real-time queries need no join.
- **Partitioning:** the table is partitioned by day, which is also how Iceberg
  prunes history.
  - **Creation:** the sink creates each day's partition as events arrive. Fluss's
    auto-partitioning is off, because its retention drops old partitions and
    would drop a backfill of older events before it is tiered.
- **Buckets:** a transaction's events stay in one bucket, in order. The bucket
  key is `transaction_id` alone, because tiering to Iceberg takes at most one
  bucket key.

### Queries

The ADR-036 Gold reports, `FLOW_SUMMARY` first, are rewritten in Flink SQL:
in batch over the Iceberg table, and in streaming over the Fluss table. The same fixture must give the same numbers in DuckDB and in
Flink.

## Release gates (v2.2.0)

1. **No loss:**
   - stop Fluss in the middle of a load, then restart it;
   - the exporter resumes from its cursor;
   - the Fluss table's count per `(tenant, transaction)` equals the log's.
2. **Latency:** p99 from `occurred_at` to the row being readable in Fluss is
   below 1 s with CDC, measured over 1,000 sagas.
3. **Tiering:** after the tiering interval, an Iceberg query returns the
   expected historical row count.
4. **Parity:** the Flink SQL `FLOW_SUMMARY` matches DuckDB's on the same log.
5. **No blocking I/O on the event loop**, and 90%+ coverage of the exporter
   and the sink.
6. **Local environment:**
   - it runs from the binary distributions of Fluss, Flink and MinIO (JDK 17),
     with or without Docker;
   - a monitoring guide and a Grafana dashboard ship with it.

## Alternatives Considered

- **In-process listener (the 2024 design, PR #67):** rejected.
  - It sees only the orchestrated sagas of the process that runs them.
  - It loses buffered events on a crash.
  - It has no tenant or deduplication key.
- **Writing Iceberg from Python (pyiceberg):** rejected.
  - It duplicates the tiering Fluss already does with exactly-once semantics.
  - It produces many small files unless compaction is added.
- **Direct Iceberg, without Fluss:** rejected. It cannot serve sub-second
  queries, and commit latency is seconds to minutes.
- **Kafka + ClickHouse:** rejected.
  - It means two systems and duplicated data.
  - ClickHouse is not an open lakehouse format.
- **Apache Paimon:** considered. It is the same idea, but Fluss focuses on
  sub-second streaming and tiers to Iceberg too.
- **The outbox relay as the transport:** rejected for this purpose.
  - `saga_outbox` carries only what choreography publishes, not the lifecycle
    events of orchestrated sagas.
  - Its rows are deleted after delivery.

## Consequences

**Positive:**
- **One source:** a single, durable, tenant-aware stream covers both
  coordination styles.
- **No new delivery code:** at-least-once reading and idempotent writes give
  exactly-once tables.
- **Open history:** Iceberg history can be read by any engine.

**Negative:**
- **Operations:** a Fluss cluster and a Flink cluster are needed for tiering.
- **Infrastructure:** the Iceberg tiering needs Hadoop and iceberg-aws JARs on
  Flink.
- **Schema changes:** the Fluss table schema must evolve with the log, and the
  tiering job fails while the lake schema diverges.

**Mitigations:**
- **Optional:** everything is opt-in, and the embedded DuckDB pipeline remains
  the zero-infrastructure option.
- **Packaging:** sagaz ships local scripts, Kubernetes manifests and the DDL.
- **Versioning:** the schema is versioned with `event_version`.

## Implementation Plan (v2.2.0)

1. **Ordered reading of the log:** add `xid8` (PostgreSQL) and a rowid order
   (SQLite), plus `saga_export_cursor` and a `SagaLogReader` (cursor and CDC).
2. **Exporter and Fluss sink:** `SagaLogExporter(reader, sink)` acknowledges
   after the sink. `FlussSink` uses `pyfluss` and is tested with a fake client.
3. **Tables and tiering:** Fluss DDL, catalog and warehouse configuration, and
   local scripts for Fluss, Flink and MinIO.
4. **Queries:** the Gold reports in Flink SQL, the Grafana dashboard and the
   guide.
5. **Integration and gates:** the release gates above, run against a real
   cluster.

## Revision notes

PR #67 is superseded and closed:
- its `POST /api/v1/rows` call to Fluss does not exist, since Fluss is reached
  through its clients over RPC;
- an Iceberg REST catalog stores metadata only and has no endpoint for rows;
- a failed flush dropped up to half the batch;
- it did blocking `urllib` calls in coroutines.

## References

- [Apache Fluss](https://fluss.apache.org/)
- [Fluss Python client](https://fluss.apache.org/docs/next/apis/python/api-reference/)
- [Fluss tiering service](https://fluss.apache.org/docs/next/streaming-lakehouse/tiering-service/)
- [Fluss and Iceberg](https://fluss.apache.org/docs/next/streaming-lakehouse/integrate-data-lakes/iceberg)
- [Apache Iceberg](https://iceberg.apache.org/)
- [ADR-011: CDC Support](adr-011-cdc-support.md)
- [ADR-036: Embedded analytics pipeline](adr-036-sqldim-analytics-pipeline.md)
- [ADR-041: Unified saga log](adr-041-unified-saga-log.md)

## Decision Makers

- @brunolnetto (Maintainer)

## Changelog

| Date | Change |
|------|--------|
| 2024-12-27 | Initial proposal |
| 2026-11-19 | Revised on the unified saga log; accepted for v2.2.0 |
