# Streaming and Historical Analytics: Fluss and Iceberg

The embedded pipeline (`SagaAnalyticsPipeline`, ADR-036) analyzes a saga log
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
restarted exporter resumes where it stopped. While Fluss is unreachable it
backs off and retries; nothing is lost.

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

## Limits

- **Freshness:** the Iceberg table is behind the log by the table's freshness.
  Set it with `--freshness`, which defaults to 3 minutes in Fluss.
- **No streaming:** both reports need batch mode. Flink's streaming mode
  supports only Top-N rankings and windows on a watermarked time attribute.
- **No union read:** Fluss 1.0 cannot read a primary-key table in batch as a
  union of Fluss and Iceberg. Query history from the `iceberg` catalog.
- **Python 3.13:** `pyfluss` 1.0 has no wheel for it yet, so it must be built
  from source with a Rust toolchain.
