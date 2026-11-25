# Step charts: where every step is, and resuming compensation

By default a saga's state machine tracks the saga only: `executing`, `compensating`,
`rolled_back` and so on. With **step charts** (StateChart phase 2,
[ADR-040](../architecture/adr/adr-040-statechart-saga-lifecycle.md)), each step has a
region of its own. The configuration the saga reports and persists then says where every
step is, and an interrupted compensation can be finished by another process.

## Turning it on

```python
saga = Saga("order", use_step_statechart=True)
# or for every saga: configure(SagaConfig(..., use_step_statechart=True))
```

With the flag off, sagas run exactly as before. The flag changes only the configuration;
statuses, results, `current_state` and stored statuses are the same.

The declarative (decorator) `Saga` takes the same flag, as an argument, a class attribute
or from `SagaConfig`:

```python
class OrderSaga(Saga):
    saga_name = "order"
    use_step_statechart = True
```

## What the configuration says

While the saga runs, `saga.state_configuration` holds the lifecycle and each step's state:

```python
[
    "active", "lifecycle", "compensating", "steps",
    "step/reserve", "step/reserve/compensating",
    "step/charge",  "step/charge/compensated",
    "step/ship",    "step/ship/failed",
]
```

- **Step states:** `pending`, `executing`, `completed`, `failed`, `compensating`,
  `compensated`, `compensation_failed` and `tainted`.
- **Pivots** (`@step(..., pivot=True)`, declarative sagas):
  - once a pivot completes, the completed steps it depends on become `tainted`;
  - a pivot's region has no compensation states;
  - the chart refuses to compensate a tainted or pivot step.
- **Step names:** they are percent-encoded, so `a/b` becomes `step/a%2Fb`.
- **After the saga ends:** the configuration is flat again (`["rolled_back"]`).

```python
from sagaz.core.execution.step_statechart import step_states, lifecycle_state

step_states(["reserve", "charge", "ship"], configuration)
# {"reserve": "compensating", "charge": "compensated", "ship": "failed"}
```

Snapshots (`ReplayConfig(enable_snapshots=True, ...)`) store the configuration. With the
flag on and the `AFTER_EACH_STEP` strategy, a snapshot is also taken after each step's
compensation. It is the checkpoint to resume from.

## Resuming a compensation

A saga stores its configuration with the saga state (`SagaConfig.storage`), and again
after each compensated step. If the process running a compensation dies, another one can
finish it from that state:

```python
saga = OrderSaga(config=config)                      # the same step definitions

await saga.pending_compensations(saga_id)   # ["reserve"]: charge was already compensated
saga.in_doubt_steps()                       # steps that were executing: check them yourself
status = await saga.resume_compensation(saga_id)     # ROLLED_BACK, or FAILED
```

- **What is pending:** `pending_compensations` reads the stored state and compensates
  nothing. It lists the steps `resume_compensation` would undo, in its order.
- **Order:** it compensates in the compensation graph's order. Compensations that had
  succeeded are not run again, and no list of completed steps is needed.
- **Locked steps:** tainted and pivot steps are left as they are.
- **In-doubt steps:** a step that was **executing** when the run stopped is not
  compensated, because whether its action took effect is unknown. It is logged, and
  listed by `in_doubt_steps()`.
- **Idempotency:** a step that was **compensating** has its compensation run again, so
  compensations should be idempotent.
- **Event log:** if the saga is event-sourced, the outcome is recorded there too.
- **Forward re-execution:** resuming forward execution is `SagaReplay`'s job
  ([saga replay](saga-replay.md)).

### Classic engine

The classic `sagaz.core.saga.Saga` does not store its state, so you give it the
configuration and the completed steps yourself, from a snapshot:

```python
snapshot = await storage.get_latest_snapshot(saga_id)

saga = build_order_saga(use_step_statechart=True)       # the same step definitions
await saga.restore_state(snapshot.configuration, snapshot.completed_steps)
saga.pending_compensations()
result = await saga.resume_compensation()   # a SagaResult: ROLLED_BACK, or FAILED
```

`restore_state` refuses a configuration that is not one of this saga's chart, and steps
it does not define. Moving to `sagaz.Saga`:

| Classic engine | `sagaz.Saga` |
|---|---|
| `await saga.restore_state(configuration, completed_steps)` | Not needed: the state is loaded from `SagaConfig.storage` |
| `saga.pending_compensations()` | `await saga.pending_compensations(saga_id)` |
| `saga.in_doubt_steps()` | `saga.in_doubt_steps()`, after either call above |
| `await saga.resume_compensation()` → `SagaResult` | `await saga.resume_compensation(saga_id)` → `SagaStatus` |
| Reverse completion order | The compensation graph's order |
