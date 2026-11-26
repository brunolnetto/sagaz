# Pivots and forward recovery

Some steps cannot be undone: a payment captured, a parcel handed to a carrier, a message
sent. Such a step is a **pivot**. Before it, a failed saga rolls back. After it, the saga
can only move forward.

## A pivot

```python
from sagaz import Saga, action, compensate

class OrderSaga(Saga):
    saga_name = "order"

    @action("reserve")
    async def reserve(self, ctx): ...

    @compensate("reserve")
    async def release(self, ctx): ...

    @action("charge", depends_on=["reserve"], pivot=True)     # the point of no return
    async def charge(self, ctx): ...

    @action("ship", depends_on=["charge"])
    async def ship(self, ctx): ...
```

Once `charge` completes, it is not compensated, and neither are the steps it depended on
(`reserve`): they are *tainted*, because undoing them would contradict a payment that
stands.

## When a step fails after the pivot

By default the saga undoes what is still reversible (the steps that completed *after* the
pivot and have a compensation), keeps the pivot and its ancestors, and raises
`SagaFailedError` with the status **`PARTIALLY_COMMITTED`**:

```python
from sagaz import SagaFailedError, SagaStatus

try:
    await OrderSaga().run(order)
except SagaFailedError as failure:
    if failure.status == SagaStatus.PARTIALLY_COMMITTED:
        ...   # the customer was charged and the order did not ship: someone must act
```

| `failure.status` | What happened |
|---|---|
| `ROLLED_BACK` | Everything that completed was undone |
| `PARTIALLY_COMMITTED` | A pivot completed. What could be undone was; the pivot and its ancestors stay done |
| `FORWARD_RECOVERY` | The saga stopped after a pivot without undoing anything, and waits for a person |
| `FAILED` | A compensation failed too |

Before 2.6.0, a saga that failed after a pivot reported `ROLLED_BACK`.

## Recovering forward

Give the step a handler that decides what to do instead of rolling back. It gets the saga
context and the step's error, and returns a `RecoveryAction`:

```python
from sagaz import RecoveryAction, forward_recovery

class OrderSaga(Saga):
    ...

    @forward_recovery("ship", max_retries=3)
    async def recover_shipping(self, ctx, error):
        if isinstance(error, CarrierUnavailable):
            ctx["carrier"] = "backup"                   # the retried step reads it
            return RecoveryAction.RETRY_WITH_ALTERNATE
        await open_support_ticket(ctx["order_id"], error)
        return RecoveryAction.MANUAL_INTERVENTION
```

| The handler returns | The saga |
|---|---|
| `RETRY`, `RETRY_WITH_ALTERNATE` | Runs the step again, with its own retries and timeout. At most `max_retries` times (default 3) |
| `SKIP` | Leaves the step failed, with no result and no compensation, and goes on. The steps that depend on it run: put in the context what they need |
| `MANUAL_INTERVENTION` | Stops. Nothing is compensated, and the status is `FORWARD_RECOVERY` |
| `COMPENSATE_PIVOT` | Rolls everything back, the pivot and its ancestors included. The status is `ROLLED_BACK`. Use it only if the pivot can be undone after all (a refund) |

- **Only after a pivot:** the handler is asked when its step is downstream of a pivot that
  completed. A step that fails before the pivot, or in a branch that does not follow it,
  rolls back as usual.
- **When recovery cannot go on:** retries that run out, a handler that raises, one that
  takes longer than its `timeout_seconds` (default 30), and an answer that is not a
  `RecoveryAction` all stop the saga in `FORWARD_RECOVERY`. sagaz does not undo a saga whose
  handler was written to move it forward.
- **A stopped saga:** its state is stored with the status `forward_recovery`, and
  `failure.failed_step` names the step. Nothing continues it on its own. If the saga
  takes snapshots, replay it from that step once the cause is fixed
  ([saga replay](saga-replay.md)).

## In a choreography

A handler can be a pivot too: `@on_event("stock.reserved", pivot=True)`. Once it
completes, every participant keeps what it had done in the transaction, and a
transaction compensated after it ends `partially_committed`, as here. See
[Pivots in a choreography](../patterns/choreography.md#pivots). There is no forward
recovery for a choreography yet
([#665](https://github.com/brunolnetto/sagaz/issues/665)).

## What the statuses mean elsewhere

- **The saga's stored state**, `SagaFailedError.status`, listeners (`on_saga_failed`) and
  `SagaOrchestrator.get_statistics()` report the four statuses above.
- **Event-sourced sagas and the unified saga log** record a partially committed saga as
  rolled back, and one that stopped for forward recovery as failed: their event stream has
  no event of its own for the two statuses yet.
