# Migrating from the classic Saga

`sagaz.core.saga.Saga` is the imperative engine that came before `sagaz.Saga`. Since 2.6.0
`sagaz.Saga` has everything it had, so creating a classic saga emits a
`DeprecationWarning`, and 3.0 removes the class. This page maps one to the other.

## The same saga, both ways

```python
# Classic
from sagaz.core.saga import Saga

saga = Saga(name="order")
await saga.add_step("reserve", reserve, release)
await saga.add_step("charge", charge, refund)          # runs after the previous step
saga.context.set("order_id", "o-1")
result = await saga.execute()                          # a SagaResult; never raises
if not result.success: ...
```

```python
# sagaz.Saga
from sagaz import Saga, SagaFailedError

saga = Saga()
saga.saga_name = "order"
saga.add_step("reserve", reserve, release)
saga.add_step("charge", charge, refund, depends_on=["reserve"])
try:
    context = await saga.run({"order_id": "o-1"})      # the final context
except SagaFailedError as failure: ...                 # failure.status, .failed_step
```

Most sagas read better declared as a class, with `@action` and `@compensate`: see
[Your first saga service](first-saga-service.md).

## What changes

| Classic `sagaz.core.saga.Saga` | `sagaz.Saga` |
|---|---|
| `Saga(name="order")` | `saga_name = "order"` on the class, or `saga.saga_name = "order"` |
| `await saga.add_step(...)` | `saga.add_step(...)`: not awaited |
| A step runs after the previous one unless `dependencies=` says otherwise | A step has no dependency unless `depends_on=[...]` says so: steps without one run in parallel. **Chain your steps explicitly** |
| `dependencies={"a"}` | `depends_on=["a"]` |
| `timeout=30.0` | `timeout_seconds=30.0` |
| An action gets a `SagaContext` (`ctx.get(...)`, `ctx.set(...)`) | An action gets the context `dict`, and returns a `dict` that is merged into it |
| A compensation gets `(result, ctx)` | A compensation gets `(ctx)`: the step's result is in the context |
| `saga.context.set(key, value)` before running | `await saga.run({key: value})` |
| `result = await saga.execute()`, a `SagaResult` that never raises | `context = await saga.run(...)`, which raises `SagaFailedError` when the saga fails |
| `result.status`, `result.error`, `result.compensation_errors` (a list) | `failure.status`, `failure.__cause__`, `failure.compensation_errors` (a dict by step) |
| `saga.saga_id`, generated when the saga is created | `await saga.run(ctx, saga_id="...")`; the id is in the returned context |

## Features

| Feature | Classic | `sagaz.Saga` |
|---|---|---|
| State storage | None: you save it yourself | `SagaConfig(storage=...)`: the saga saves its own state, and a saga id runs once |
| Parallel failure strategy | `Saga(failure_strategy=...)` | `SagaConfig(failure_strategy=..., failure_grace_period=...)` ([configuration](configuration.md#parallel-failure-strategies)) |
| Retry backoff | `Saga(retry_backoff_base=...)` | `saga.retry_backoff_base = ...` |
| Per-step idempotency | In memory only | `@action(..., idempotency_key="charge-{order_id}")`, durable ([one effect, one run](first-saga-service.md#one-effect-one-run)) |
| Snapshots | `Saga(replay_config=..., snapshot_storage=...)` | `SagaConfig(replay_config=..., snapshot_storage=...)` ([saga replay](saga-replay.md)) |
| Replay | `await saga.execute_from_snapshot(snapshot, override)` | `await saga.run_from_snapshot(snapshot, override)`; `SagaReplay` takes either kind |
| Resuming a compensation | `restore_state(...)`, then `resume_compensation()` | `await saga.resume_compensation(saga_id)` ([step charts](step-statechart.md#resuming-a-compensation)) |
| Step chart | `Saga(use_step_statechart=True)` | `SagaConfig(use_step_statechart=True)` |
| Orchestrator | `await orchestrator.execute_saga(saga)` | `await orchestrator.run(saga, context)` |
| A deadline for the whole saga | Not available | `await saga.run(ctx, deadline=30)` ([a deadline for the whole saga](first-saga-service.md#a-deadline-for-the-whole-saga)) |
| Tenancy, listeners, multi-region, `sagaz saga show` | Not available | Available |

## Things to check when you migrate

- **Step order.** Classic steps ran one after another by default. In `sagaz.Saga`, steps
  with no `depends_on` run at the same time, so add the dependency a sequence needs.
- **Failures raise.** Code that inspected `result.success` now catches `SagaFailedError`.
- **Cancelled parallel steps.** With the default `FAIL_FAST_WITH_GRACE`, a step still
  running two seconds after a sibling failed is cancelled, and not compensated. Use
  `WAIT_ALL` if a step must never be interrupted.
- **Step method names.** A step method of a `sagaz.Saga` subclass must not start with an
  underscore: such a method is not collected.
