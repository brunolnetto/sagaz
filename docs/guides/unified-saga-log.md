# Unified saga log

The unified saga log is **one OLTP model** that orchestrated and choreographed sagas
both write to. Design: [ADR-041](../architecture/adr/adr-041-unified-saga-log.md).
Milestone: v2.1.0.

!!! note "Status"
    - **Phase 1 (#464):** the tables, the store and `sagaz migrate unify`.
    - **Phase 2 (#465):** orchestrated sagas record on the log.
    - **Phase 3 (#466):** choreography writes to it, with atomic publishing.
    - **Phase 4 (#467):** analytics reads it.

## Tables

| Table | One row per | Replaces |
|---|---|---|
| `saga_transaction` | distributed transaction: `coordination` is `orchestrated` or `choreographed`, plus its `flow`, `status`, `initiator`, and `version` for optimistic concurrency | `sagas`, the tracker's `choreography` records |
| `saga_activity` | unit of work of one participant: a step, or a handled event with a compensation. `__transaction__` rows mark a participant's end of a transaction, and the compensation tombstone | `saga_steps`, `choreography_actions`, `choreography_transactions` |
| `saga_log_event` | log entry, **append-only**, numbered per transaction (`sequence`), with `kind`, `source`, `causation_id` and `payload` | `saga_events`, the events inside tracker records |
| `saga_snapshot` | projection or replay snapshot | `saga_event_snapshots`, `saga_snapshots` |
| `saga_participant` | service, with the database role it writes as | — |
| `saga_delivery` | event consumed by a participant | `choreography_deliveries`, `consumer_inbox` |
| `saga_deadline` | time limit owned by a participant, with its lease | `choreography_deadlines` |

Every table is tenant-scoped (ADR-020). `saga_outbox` gains `log_event_id`.

```python
from sagaz.core.storage.saga_log import (
    Coordination, EventKind, LogEvent, LogWrite, StatusChange, Transaction,
    create_saga_log_store,
)

async with create_saga_log_store("postgresql://...") as log:
    await log.write(LogWrite(                       # one database transaction
        transaction=Transaction("t-1", "order", Coordination.ORCHESTRATED, initiator="orders"),
        events=[LogEvent("t-1", "SagaStarted", EventKind.LIFECYCLE, source="orders")],
    ))
    await log.write(LogWrite(status=StatusChange("t-1", "completed", expected_version=1)))
    events = await log.events("t-1")                # in sequence order
```

A `LogWrite` is applied atomically: insert the transaction (once), change its status
if it is still at `expected_version` (`ConcurrencyError` otherwise), append the events,
upsert the activities, then set or clear deadlines. Stores: `postgresql://`
(reference), `sqlite://<path>` and `memory://`.

## Recording orchestrated sagas

Opt in per saga, or for every saga through `SagaConfig`:

```python
class OrderSaga(Saga):
    class Meta:
        storage_layout = "unified"          # default: "classic" ("legacy" also accepted)
        saga_log = "postgresql://..."       # or a SagaLogStore
        participant = "orders-service"      # who runs the steps (default: "orchestrator")
        snapshot_threshold = 50

configure(SagaConfig(storage_layout="unified", saga_log="postgresql://..."))  # all sagas
legacy = sagaz.core.saga.Saga(name="billing", saga_log="postgresql://...", participant="billing")
```

Each lifecycle transition is **one** atomic write: the event (`SagaStarted`,
`StepExecuted`, `StepFailed`, `CompensationStarted`, `StepCompensated`,
`StepCompensationFailed`, `SagaCompleted`, `SagaRolledBack`, `SagaFailed`), the step's
activity (status, attempt, region, result, error, duration) and the transaction's status
change (`executing` → `compensating` → `completed` / `rolled_back` / `failed`, checked
against its `version`). The current state and the log cannot diverge. When the saga
ends, its accumulated context (the initial context plus step results) is stored on the
transaction.

The unified layout includes event sourcing: there is no separate event store. The
ADR-033 view reads the log, so projections, snapshots and `sagaz event-log --layout
unified` work as before. As with the event store, a failed write is logged and counted
and does not fail the saga.

Recording costs about the same as the ADR-033 event store: 0.93× per event on SQLite,
where both are dominated by the commit to disk.

## Choreography on the log

Give the engine the log. Participant state then lives on the unified tables, and
publishing becomes atomic:

```python
engine = ChoreographyEngine(bus, completion_events={"order.shipped"},
                            saga_log="postgresql://...")
tracker = ChoreographyTracker(bus, completion_events={"order.shipped"},
                              saga_log="postgresql://...")
```

- **Atomic record-and-publish.** When a handler `emit()`s, one database transaction
  records the action it completed, appends the new event to the log and queues it
  in the outbox. `begin()` also inserts the `choreographed` transaction, with its
  `flow` (the event type) and `initiator`. `engine.relay`, the standard
  `OutboxWorker` with an `EventBusBroker`, then publishes the outbox on the bus.
  Before, a crash between "state updated" and "event published" lost one of them.
- **Delivery:** at least once. A message whose publication fails, for example
  because the bus is down, is retried on the next relay poll, up to `max_retries`
  times (100 by default), and then goes to the outbox dead letter. Participants
  deduplicate by `event_id`. The relay can also run from CDC (ADR-011).
- **Participant state on the unified tables:**
    - a completed action is a `saga_activity`, with its triggering event kept for
      compensation;
    - the end of a participant's part is its `__transaction__` marker
      (`compensated` is the tombstone of #446);
    - deliveries are `saga_delivery` rows and deadlines are `saga_deadline` rows.

  Replicas of a participant share them through the database, so any replica can
  compensate what another did.
- **The tracker is a projection.** With `saga_log`, `ChoreographyTracker` derives a
  transaction's status from its log entries (no JSON record) and keeps the
  transaction row's `status` in step. `sagaz choreography status <id> --saga-log
  postgresql://...` reads the same projection.

## Analytics

`SagaAnalyticsPipeline` reads the log directly (`sagaz[analytics]`):

```python
async with create_saga_log_store("postgresql://...") as log:
    with SagaAnalyticsPipeline(log) as pipeline, system_scope():
        await pipeline.run()
        pipeline.query(SagaQueries.FLOW_SUMMARY)   # orchestrated and choreographed, per flow
```

Every existing Gold report works on the log. `FLOW_SUMMARY` adds one row per
coordination style and flow, with completed, compensated, failed and in-flight counts,
the compensation rate and p50/p95 durations. After `sagaz migrate unify`, the reports
match those of the old layout, apart from timings.

## Exporting the log

An exporter (the Fluss sink of ADR-013, or your own) reads committed events of
every tenant with a `SagaLogReader`. It resumes after the position it
acknowledged last, which is stored in `saga_export_cursor` in the log's database:

```python
reader = SagaLogReader(log, "fluss")
while batch := await reader.read():
    await sink.write(batch.events)   # ExportedEvent: event, coordination, flow
    await reader.acknowledge(batch)  # only after the sink accepted it
```

Delivery is at least once. A crash between the write and `acknowledge` repeats
the batch, so the sink must be idempotent, for example by keying rows on
`(tenant_id, transaction_id, sequence)`.

The order never lets a later commit land before the position:
- **SQLite:** the rowid, since there is one writer at a time.
- **PostgreSQL:** the writing transaction's id (`writer_xid`), and only rows of
  transactions older than every one still running are read. A long-running
  transaction therefore delays the export until it ends, and its events are
  never skipped.

### To Apache Fluss

`SagaLogExporter` runs that loop in the background. It acknowledges a batch only
after the sink accepted it, and it backs off while the sink is down. `FlussSink`
writes to a Fluss primary-key table on `(dt, tenant_id, transaction_id, sequence)`,
so a repeated batch is an upsert of the same rows. With the datalake enabled,
Fluss's tiering service moves the table to Iceberg (ADR-013).

```python
from sagaz.core.storage.saga_log import SagaLogExporter, SagaLogReader
from sagaz.integrations.fluss import FlussSink

exporter = SagaLogExporter(SagaLogReader(log, "fluss"), FlussSink("fluss:9123"))
await exporter.start()           # exporter.metrics(): exported, errors, lag_seconds
```

From the command line:

```bash
sagaz analytics export --saga-log postgresql://... --to fluss://fluss:9123   # continuous
sagaz analytics export --saga-log ... --to fluss://... --once                # catch up, exit
sagaz analytics fluss-ddl                                                    # Flink SQL DDL
```

Install it with `pip install 'sagaz[fluss]'`. pyfluss 1.0 ships wheels up to
Python 3.12; on 3.13 it builds from source, which needs a Rust toolchain.

## Sharing one database between services

The log holds coordination state, not domain data, so the services of an organization
can share it, as they would share Temporal's or Camunda's database. Isolation comes
from database roles:

1. **The platform role** (the one sagaz migrations, coordinators and the tracker
   connect as) owns the schema. It creates the schema on first use, or when you run
   `sagaz migrate unify`.
2. **One role per service.** Grant it the service privileges and register it as its
   participant:

    ```python
    from sagaz.core.storage.saga_log import Participant
    from sagaz.core.storage.saga_log._pg_schema import service_role_grants

    await platform_conn.execute("CREATE ROLE svc_inventory LOGIN PASSWORD '...'")
    await platform_conn.execute(service_role_grants("svc_inventory"))
    await platform_log.register_participant(Participant("inventory", db_role="svc_inventory"))
    ```

3. The service connects as its role. Row-level security then:
    - lets it write only its own rows: activities and deliveries of `inventory`,
      events whose `source` is `inventory`, transactions it initiates, deadlines it
      owns;
    - keeps the log append-only: no `UPDATE` or `DELETE` on `saga_log_event`;
    - keeps the participant registry read-only.

Roles that are not registered as a participant, such as the platform, the tracker and
operators, are not restricted. Tenancy still applies to every role.

A service role cannot create the schema. If the platform has not created it yet, the
service's first query fails with a permission error.

## Migrating existing data

```bash
sagaz migrate unify --source postgresql://... --dry-run   # what would be copied
sagaz migrate unify --source postgresql://...             # copy into the same database
sagaz migrate unify --source sqlite:///old.db --target postgresql://...
```

It reads, across every tenant:

- sagas and their steps, through any saga storage;
- the choreography tracker's records;
- the event store;
- choreography participant state, deliveries and deadlines;
- `consumer_inbox`;
- projection and replay snapshots.

It writes them into the unified tables and leaves the old tables untouched. Running it
again adds nothing: transactions are inserted once, activities, snapshots and
deadlines are upserted, deliveries are claimed once, and a transaction's log is only
filled while it is empty.

Orchestrated steps migrated from the old layout are attributed to the participant
`orchestrator`, because the old tables do not record which service ran them.
