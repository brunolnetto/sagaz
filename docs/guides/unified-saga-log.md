# Unified saga log

The unified saga log is **one OLTP model** that orchestrated and choreographed sagas
both write to. Design: [ADR-041](../architecture/adr/adr-041-unified-saga-log.md).
Milestone: v2.1.0.

!!! note "Status"
    **Phase 1 (#464)** delivers the tables, the store and the migration of existing
    data. The engines write to the log in phases 2 (orchestration, #465) and 3
    (choreography, #466), and analytics reads it in phase 4 (#467). Until then, sagas
    keep using the current tables, which `sagaz migrate unify` copies into the log.

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
