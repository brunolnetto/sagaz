# Change Data Capture (CDC) for the outbox

By default the outbox worker **polls** `saga_outbox` for pending events. In **CDC
mode** it instead receives each inserted row from PostgreSQL's write-ahead log as the
transaction commits, and publishes it right away. Saga code does not change: sagas
keep writing to the outbox in the same transaction as their state. Design:
[ADR-011](../architecture/adr/adr-011-cdc-support.md); issue #50.

## Choosing a source

| | `PgLogicalSource` | `DebeziumKafkaSource` |
|---|---|---|
| Reads | PostgreSQL logical replication directly (`pgoutput`) | A Kafka topic written by Debezium's PostgreSQL connector |
| Extra infrastructure | None (`wal_level=logical`, a replication slot) | Kafka, Kafka Connect, Debezium |
| Good fit | PostgreSQL-only deployments | Teams already running Kafka/Kafka Connect, or several consumers of the change stream |
| Setup | Creates its publication and slot on start (`create=True`) | Register the connector: [CDC with Debezium](cdc-debezium.md) |

Both need the `cdc` extra (`pip install 'sagaz[cdc]'`: `psycopg2-binary`, `aiokafka`,
`httpx`), and both deliver **at least once**: a batch is acknowledged to the source
(replication slot position, Kafka offsets) only after every event in it was handled.
Consumers deduplicate by `event_id`, for example with the consumer inbox.

### PostgreSQL prerequisites (`PgLogicalSource`)

- `wal_level = logical` (requires a restart), and `max_replication_slots` /
  `max_wal_senders` of at least one each for the worker.
- A role with `REPLICATION` (or a superuser). Logical decoding is **not filtered by
  row-level security**: the replication role sees every tenant's rows, so treat it as
  privileged. Each event keeps its own `tenant_id`, and the worker publishes it in that
  tenant's scope.
- A replication slot retains WAL until it is acknowledged. A stopped worker, or a slot
  nobody uses any more, makes the disk grow. Set `max_slot_wal_keep_size`, monitor
  `pg_replication_slots`, and call `PgLogicalSource(...).drop_slot()` when retiring a
  source.

## Running the worker in CDC mode

In code:

```python
from sagaz.core.outbox.worker import OutboxWorker
from sagaz.integrations.cdc import PgLogicalSource

source = PgLogicalSource("postgresql://replicator:...@db/sagas")
worker = OutboxWorker(storage, broker, config, cdc_source=source)
await worker.start()  # streams until worker.stop()
```

With the worker's entry point (`python -m sagaz.core.outbox.worker`), the environment
selects the mode:

| Variable | Default | Meaning |
|---|---|---|
| `SAGAZ_OUTBOX_MODE` | `polling` | `cdc` enables CDC mode |
| `SAGAZ_CDC_SOURCE` | `pg_logical` | `pg_logical` or `debezium` |
| `SAGAZ_CDC_DSN` | `DATABASE_URL` | Replication DSN (`pg_logical`); can use a dedicated role |
| `SAGAZ_CDC_SLOT` / `SAGAZ_CDC_PUBLICATION` | `sagaz_outbox` / `sagaz_outbox_pub` | Slot and publication (`pg_logical`) |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka (`debezium`) |
| `SAGAZ_CDC_TOPIC_PREFIX` / `SAGAZ_CDC_GROUP_ID` | `sagaz` / `sagaz-cdc` | Debezium topic prefix and consumer group |
| `SAGAZ_CDC_SWEEP_INTERVAL` | `30` | Seconds between sweeps; `0` disables the sweep |
| `SAGAZ_CDC_SWEEP_MIN_AGE` | `30` | Only events pending longer than this are swept |

### Hybrid recovery: the sweep

Each streamed event is published through the same path as a polled one: tenant
scope, broker, `SENT` status, retries and the DLQ. A failed publish puts the event
back to `PENDING` with an `UPDATE`, but the change stream only carries inserts, so it
would never deliver the event again. A slow **sweep** therefore claims events that
have been pending longer than `SAGAZ_CDC_SWEEP_MIN_AGE` and processes them as polling
would. The sweep also covers:

- retries after failed publishes;
- rows written before the slot or connector existed (Debezium's `snapshot.mode=no_data`
  does not read them), so switching from polling to CDC needs no manual drain;
- anything inserted while the worker was down beyond the slot's retention.

Fresh events are left to the stream. An event is published twice only if the stream
lags behind the sweep age, which the at-least-once contract already allows.

## Metrics

Exported with the worker's other Prometheus metrics (`prometheus-client` installed):

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `sagaz_cdc_lag_seconds` | histogram | `source` | From the commit of the outbox insert to the end of its processing |
| `sagaz_cdc_events_total` | counter | `source` | Events received from the source and processed |
| `sagaz_cdc_errors_total` | counter | `source`, `kind` | `kind="event"`: an event's processing raised; `kind="stream"`: the source failed and the worker stopped |

Publish failures themselves are counted by the existing
`sagaz_outbox_failed_events_total` and retried by the sweep. The outbox Grafana dashboards
(Kubernetes and local) have a **CDC** row with lag p50/p95/p99, throughput and errors
per source. Useful alerts:

```promql
histogram_quantile(0.99, sum(rate(sagaz_cdc_lag_seconds_bucket[5m])) by (le)) > 1
increase(sagaz_cdc_errors_total{kind="stream"}[5m]) > 0
```

Also watch the slot itself, since lag that the worker cannot see accumulates there:

```sql
SELECT slot_name, active,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS retained
FROM pg_replication_slots;
```

## Performance

On a laptop, CDC kept up with ~7,400 events/s with a millisecond lag (p50 8 ms at
1,000 events/s), where polling saturated at ~1,500 events/s with a lag of seconds. See
[CDC outbox: throughput and lag](../benchmarks/cdc-outbox.md).

## Verified

- An end-to-end test runs a declarative saga writing its state and outbox events to
  PostgreSQL in two tenants. A CDC-mode worker reading `PgLogicalSource` publishes
  every event, with its tenant, **within 200 ms of the commit**
  (`tests/integration/test_cdc_worker_e2e.py`).
- `PgLogicalSource` was tested against a real PostgreSQL 16, including that a
  `REPLICATION NOBYPASSRLS` role receives every tenant's rows. Its `pgoutput` decoder
  was checked against bytes captured from the server.
- `DebeziumKafkaSource` has unit tests over the envelope variants and offset commits.
  Its container test (PostgreSQL, Kafka, Debezium Connect) is in
  `tests/integration/test_cdc_debezium.py`.
