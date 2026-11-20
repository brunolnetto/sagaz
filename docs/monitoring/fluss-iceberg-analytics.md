# Streaming and Historical Analytics: Fluss and Iceberg

The embedded pipeline (`SagaAnalyticsPipeline`, ADR-043) analyzes a saga log
from a single process. For every service writing to one log, with history kept
for months, sagaz exports the unified saga log (ADR-041) to
[Apache Fluss](https://fluss.apache.org/), and Fluss tiers it to
[Apache Iceberg](https://iceberg.apache.org/). The design is in ADR-013.

```
services ─▶ saga_log_event ─▶ sagaz analytics export ─▶ Fluss ─▶ tiering job ─▶ Iceberg
            (PostgreSQL/SQLite)   (at least once)        (PK table)   (Flink)      (history)
                                                                                     │
                                                       sagaz analytics flink-sql ◀───┘
```

## What gets exported

There is one row per log event in `sagaz.saga_log_event`, keyed on
`(dt, tenant_id, transaction_id, sequence)`. The key makes redelivery
harmless: an event written twice is the same row.

| Column | |
|--------|-|
| `tenant_id`, `transaction_id`, `sequence` | The event's key in the log. |
| `event_id`, `event_type`, `kind` | The kind is `lifecycle`, `business`, `compensate` or `compensated`. |
| `coordination`, `flow` | Copied from the transaction: `orchestrated` or `choreographed`, and the saga name or first event type. |
| `source`, `causation_id`, `payload` | `payload` is JSON. |
| `occurred_at`, `occurred_at_ms` | `occurred_at_ms` is epoch milliseconds, for Flink SQL. |
| `event_version`, `dt` | `dt` is the UTC day and the partition. |

The log alone tells every transaction's status:

- **Orchestrated sagas** record `SagaStarted`, `CompensationStarted`,
  `SagaCompleted`, `SagaRolledBack` and `SagaFailed`.
- **Choreographed transactions:** the `ChoreographyTracker` records each status
  change as a `TransactionStatusChanged` lifecycle event, with the payload
  `{"status": ..., "previous": ...}`. Its source is the transaction's
  initiator.
- **Migrated data:** `sagaz migrate unify` adds that event to choreographed
  transactions that had already finished.

## Running it locally

`scripts/lakehouse/lakehouse.sh` runs Fluss, Flink and Iceberg from pinned
binaries, without Docker (see its README):

```bash
export ICEBERG_JDBC_URL=jdbc:postgresql://localhost:5432/iceberg
scripts/lakehouse/lakehouse.sh fetch && scripts/lakehouse/lakehouse.sh start
scripts/lakehouse/lakehouse.sh tiering

pip install 'sagaz[fluss]'   # pyfluss: wheels up to Python 3.12
sagaz analytics export --saga-log postgresql://... --to fluss://localhost:9123 --freshness 30s
```

The exporter keeps its position in the log's `saga_export_cursor` table, so a
restarted exporter resumes where it stopped.

### Streaming the log with CDC

On PostgreSQL, `--cdc` streams the log through logical replication instead of polling.
It needs `pip install 'sagaz[cdc]'`, `wal_level = logical` and a role with
`REPLICATION`:

```bash
sagaz analytics export --saga-log postgresql://... --to fluss://localhost:9123 --cdc
```

- **Order and timing:** changes arrive in commit order, as soon as their transaction
  commits.
- **Position:** the replication slot `sagaz_log_<name>` keeps it, and an acknowledged
  batch lets the server discard its WAL.
- **Earlier events are not streamed:** only changes committed after the slot exists
  reach the reader. Start the exporter before the services write. For events already in
  the log, run a cursor export once under another `--name`.
- **Abandoned slots:** a slot nobody reads retains WAL. Drop the slot of an exporter you
  retire. While Fluss is unreachable it
backs off and retries; nothing is lost.

### With Docker

`sagaz/deployment/resources/local/lakehouse/docker-compose.yaml` runs the same
stack in containers. Fluss runs with ZooKeeper, Flink runs the tiering job, and
Iceberg lives on S3 (RustFS), with its JDBC catalog in PostgreSQL. With
`--profile metrics`, Prometheus and Grafana run too.

```bash
cd sagaz/deployment/resources/local/lakehouse
./fetch-jars.sh && docker compose up -d
docker compose exec jobmanager /opt/flink/tiering.sh

sagaz analytics export --saga-log ... --to fluss://localhost:9124
sagaz analytics metrics --catalog-uri postgresql://iceberg:iceberg@localhost:15433/iceberg \
    --catalog-property s3.endpoint=http://localhost:9000 \
    --catalog-property s3.access-key-id=rustfsadmin \
    --catalog-property s3.secret-access-key=rustfsadmin
```

Each Fluss server listens twice:

- **`FLUSS`:** used by the containers;
- **`CLIENT`:** advertised as `localhost` (ports 9124 and 9125) and used by the
  host.

A client receives the endpoints of the listener it connected through.

### Release gates

`tests/integration/test_lakehouse_e2e.py` runs the gates of ADR-013 against
the compose. It needs `SAGAZ_TEST_LAKEHOUSE=1`, Python 3.12 for pyfluss, and
the tiering job submitted. The `Lakehouse` CI workflow runs them with 1,000
sagas.

1. **No loss:** the tablet server is stopped and restarted mid-load. The
   events in Iceberg per tenant and transaction must equal the log's.
2. **Latency:** p99 from `occurred_at` to Fluss acknowledging an event must
   be below 1 s, at a steady rate after a warm-up.
3. **Tiering:** Iceberg must hold each of the log's events exactly once.
4. **Parity:** the flow summary over Iceberg must equal the embedded
   pipeline's.

## Reports

`sagaz analytics flink-sql REPORT` prints a report in Flink SQL. Run it in
batch mode over the Iceberg table:

```bash
sagaz analytics flink-sql flow-summary > flow.sql
scripts/lakehouse/lakehouse.sh sql     # then: SET 'execution.runtime-mode' = 'batch';
```

| Report | |
|--------|-|
| `flow-summary` | Per coordination style and flow: transactions, completed, compensated, failed and in flight; the compensation rate; p50 and p95 durations. Same semantics as the embedded `SagaQueries.FLOW_SUMMARY`. |
| `throughput` | Per minute, coordination style and flow: transactions, events and compensations requested. |

On the same log, `flow-summary` in Flink and in the embedded DuckDB pipeline
agree on every count and rate. Durations agree to the millisecond, because
Flink works in milliseconds and DuckDB in microseconds.

## Prometheus and Grafana

`sagaz analytics metrics` serves the flow summary of the Iceberg history to
Prometheus (`pip install 'sagaz[iceberg]'`). It reads the table with pyiceberg,
through the catalog Fluss writes to: a pyiceberg SQL catalog reads the tables a
JDBC catalog keeps. DuckDB then computes `flow-summary`:

```bash
sagaz analytics metrics --catalog-uri postgresql://postgres@localhost:5432/iceberg \
    --warehouse file:///path/to/warehouse --port 9464 --days 30
```

The report is cached for `--refresh` seconds (60 by default), so scrapes never
wait on a table scan. A failed refresh keeps serving the last report: the
failure is counted, and the report's age keeps growing. `--days` limits the scan
to recent day partitions. `--catalog-name` must equal Fluss's
`datalake.iceberg.name`, because a SQL catalog files tables under it.

| Metric | Labels |
|--------|--------|
| `sagaz_flow_transactions` | `coordination`, `flow`, `status`: completed, compensated, failed, in_flight |
| `sagaz_flow_compensation_rate_percent` | `coordination`, `flow` |
| `sagaz_flow_duration_milliseconds` | `coordination`, `flow`, `quantile`: 0.5, 0.95 |
| `sagaz_flow_report_age_seconds`, `sagaz_flow_report_errors_total` | none |

`sagaz analytics export --metrics-port 9465` also serves the exporter's own
metrics, labelled by `exporter`:

- `sagaz_log_export_events_total`;
- `sagaz_log_export_errors_total`;
- `sagaz_log_export_lag_seconds`, the seconds since the last exported event
  occurred.

The Grafana dashboard
`sagaz/deployment/resources/local/lakehouse/grafana/dashboards/sagaz-flows.json`
("Sagaz - Saga Flows") charts both. It has variables for the Prometheus data
source, the coordination style and the flow.

## Limits

- **Freshness:** the Iceberg table is behind the log by the table's freshness.
  Set it with `--freshness`, which defaults to 3 minutes in Fluss.
- **No streaming:** both reports need batch mode. Flink's streaming mode
  supports only Top-N rankings and windows on a watermarked time attribute.
- **No union read:** Fluss 1.0 cannot read a primary-key table in batch as a
  union of Fluss and Iceberg. Query history from the `iceberg` catalog.
- **Python 3.13:** `pyfluss` 1.0 has no wheel for it yet, so it must be built
  from source with a Rust toolchain.
