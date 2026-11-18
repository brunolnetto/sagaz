# Event-sourced sagas

By default, sagaz stores each saga as one record that is overwritten as the saga
runs: you see where it ended, not how it got there. With **event sourcing**, a saga
also appends every state change to an event store: started, each step's result or
failure, each compensation, and the outcome. The saga's state is rebuilt from those
events, so you keep the complete history of every run. Design:
[ADR-033](../architecture/adr/adr-033-event-sourcing-integration.md); issue #57.

Use it when you need an audit trail, such as for compliance (GDPR, HIPAA, PCI-DSS), or to
answer "what happened to this order, and when?". It is opt-in per saga. Sagas that do
not opt in are unchanged.

## Opting in

```python
from sagaz import Saga, action, compensate


class OrderSaga(Saga):
    saga_name = "order"

    class Meta:
        storage_strategy = "event_sourced"           # default: "snapshot"
        event_store = "postgresql://user:pass@db/sagaz"
        snapshot_threshold = 50                      # default: 50

    @action("reserve")
    async def reserve(self, ctx):
        return {"reservation_id": await stock.reserve(ctx["order_id"])}

    @compensate("reserve")
    async def release(self, ctx):
        await stock.release(ctx["reservation_id"])

    @action("charge", depends_on=["reserve"])
    async def charge(self, ctx):
        return {"charge_id": await gateway.charge(ctx["order_id"], ctx["amount"])}
```

`event_store` takes a URL or a store instance:

| URL | Store | Use |
|---|---|---|
| `postgresql://...` | `PostgreSQLEventStore` | Production |
| `sqlite://<path>` | `SQLiteEventStore` | Development, tests, single node |
| `memory://` | `InMemoryEventStore` | Tests |

Sagas that share a URL share one store and its connection pool. For sagas built with
`add_step()` (no `Meta`), or to set a default for every saga, use `SagaConfig`:

```python
from sagaz import SagaConfig, configure

configure(SagaConfig(storage_strategy="event_sourced", event_store="postgresql://..."))
```

`Meta` settings take precedence over `SagaConfig`. An event-sourced saga without an
event store fails before it starts, with an error saying so.

The usual snapshot storage (`SagaConfig.storage`) is still written if you configured
one, so tools that read it keep working. The event stream is the full history.

## The events

| Event | Recorded when | Payload |
|---|---|---|
| `SagaStarted` | A run starts | `initial_context` |
| `StepExecuted` | A step's action succeeds | `step_name`, `step_result`, `duration_ms` |
| `StepFailed` | A step's action raises or times out | `step_name`, `error_type`, `error_message` |
| `CompensationStarted` | The saga starts undoing completed steps | `failed_step`, `error_type`, `error_message` |
| `StepCompensated` | A compensation succeeds | `step_name` |
| `StepCompensationFailed` | A compensation raises | `step_name`, `error_type`, `error_message` |
| `SagaCompleted` | Every step succeeded | `duration_ms` |
| `SagaRolledBack` | A step failed and the compensations succeeded | `duration_ms` |
| `SagaFailed` | A compensation failed, so effects remain | `error_message`, `duration_ms` |

Every event also has an `event_id`, its `occurred_at` time (UTC), its `sequence` in the
saga's stream (1, 2, 3, ...), the `saga_name`, the `tenant_id` and an `event_version`.
Payloads are stored as JSON. Values without a JSON form, such as custom objects, are
stored as strings.

Running a saga again with the same `saga_id` appends to the same stream. Its state
then reflects the latest run, and `runs` counts the runs.

!!! warning "The stream keeps the context"
    `SagaStarted` stores the initial context and `StepExecuted` stores each step's
    result, unencrypted. Do not put secrets there, or encrypt them yourself before
    they reach the saga.

## Reading a saga's history

From the command line:

```bash
sagaz event-log <saga-id> --store-url postgresql://...
sagaz event-log <saga-id> --tenant acme --json     # events and state as JSON
```

The store URL can also come from `SAGAZ_EVENT_STORE_URL`.

```text
Saga 7f3c... (order, tenant default): rolled_back
     1  2026-11-18 14:23:04.692  SagaStarted
     2  2026-11-18 14:23:04.694  StepExecuted            reserve  0.1 ms
     3  2026-11-18 14:23:04.695  StepFailed              charge  ValueError: card declined
     4  2026-11-18 14:23:04.695  CompensationStarted     charge  ValueError: card declined
     5  2026-11-18 14:23:04.696  StepCompensated         reserve
     6  2026-11-18 14:23:04.696  SagaRolledBack          3.1 ms
```

From code:

```python
from sagaz.core.storage.event_store import create_event_store
from sagaz.projections import load_projection

async with create_event_store("postgresql://...") as store:
    events = await store.load_stream(saga_id)        # every event, in order
    state = await load_projection(store, saga_id)    # SagaSummaryProjection
    print(state.status, state.failed_step, state.steps["charge"].error)
```

`SagaSummaryProjection` holds the status (`executing`, `compensating`, `completed`,
`rolled_back` or `failed`), the context rebuilt from the step results, each step's
status, result, error and duration, the failed step and the error.

## Snapshots

Each time a saga's stream crosses a multiple of `snapshot_threshold` events, its
projection is saved as a snapshot. `load_projection` then reads the latest snapshot
plus the events after it, instead of the whole stream. Snapshots are derived data:
the events stay, and deleting the snapshots only makes loading slower.

## Guarantees

- **Order:** each saga's events are numbered by the store. Concurrent appends to one
  stream, such as parallel steps or several processes, never share a number. The
  PostgreSQL store serializes them with an advisory lock per stream.
- **Append-only:** sagaz never updates or deletes events.
- **Recording does not fail sagas:** if the event store is unavailable, the append is
  logged and counted (`outcome="error"`), and the saga runs on. The same applies to
  the snapshot storage. The stream of that run then has a gap, so alert on the
  error counter.
- **Tenants:** events and snapshots belong to the tenant the saga runs as
  (`Saga.run(tenant_context=...)`, ADR-020). Reads return the current tenant's events
  only. In PostgreSQL, both tables use the same row-level security policy as the saga
  tables, so run the application with a role that is not a superuser.

## Metrics

| Metric | Labels |
|---|---|
| `sagaz_event_store_events_total` | `saga_name`, `event_type`, `outcome` (`appended`, `error`) |
| `sagaz_event_store_snapshots_total` | `saga_name`, `outcome` (`saved`, `error`) |

The Grafana dashboard shipped with the Kubernetes manifests has an "Event store"
panel with the event rate per saga.

## Limits

- Event sourcing applies to `sagaz.Saga`, both declarative and with `add_step()`. The
  lower-level `sagaz.core.saga.Saga` does not record events yet.
- Retention is up to you: the stream grows with every run. Archive or delete old
  streams with SQL if you must.
