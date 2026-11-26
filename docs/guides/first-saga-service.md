# Your First Saga Service

A path from "a saga that runs" to "a saga service you can operate", for a backend
engineer adding sagaz to a service. Each section is a few minutes; the
[quickstart](../quickstart.md) covers defining and running a saga.

## 1. A saga per request

Define the saga once, and run it per request with the request's id as the saga id:

```python
from sagaz import Saga, SagaConfig, action, compensate


class OrderSaga(Saga):
    saga_name = "order"

    def __init__(self, payments, inventory, **kwargs):
        super().__init__(**kwargs)
        self.payments, self.inventory = payments, inventory  # your clients, injected

    @action("reserve_inventory", timeout_seconds=5)
    async def reserve(self, ctx):
        return {"reservation_id": await self.inventory.reserve(ctx["items"])}

    @compensate("reserve_inventory")
    async def release(self, ctx):
        await self.inventory.release(ctx["reservation_id"])

    @action("charge_payment", depends_on=["reserve_inventory"], max_retries=2)
    async def charge(self, ctx):
        return {"charge_id": await self.payments.charge(ctx["order_id"], ctx["amount"])}

    @compensate("charge_payment")
    async def refund(self, ctx):
        await self.payments.refund(ctx["charge_id"])
```

- **Steps and compensations** can be `async def` or plain `def`. A step's returned dict is
  merged into the context that later steps and compensations read.
- **`max_retries`** (default 3, `SagaConfig.default_max_retries`) retries a failing
  step with exponential backoff, each attempt under `timeout_seconds` (default 60 s,
  `SagaConfig.default_timeout`).
- **Mistakes in the definition** raise `SagaDefinitionError` with the step's name: a
  `@compensate` of no step and duplicate names when the saga is created, an unknown
  `depends_on` and cycles before it runs.

## 2. Persist to PostgreSQL

```python
from sagaz import SagaConfig, configure
from sagaz.core.storage import PostgreSQLSagaStorage

config = SagaConfig(storage=PostgreSQLSagaStorage("postgresql://app@db/orders"))
configure(config)   # the default for every saga; or pass config= per saga
```

- **The schema** is created and upgraded on first use; there is no DDL to run.
- **The state** is saved when the saga starts, after each level of steps and when it
  ends. If it cannot be saved, the saga stops with `SagaPersistenceError` (and
  compensates what ran); `SagaConfig(tolerate_persistence_errors=True)` logs instead.
- **Without `storage=`**, sagas keep their state in memory, which is lost on restart:
  fine for tests, not for a service.

## 3. One request, one run

Use your request's natural key as the saga id. A saga id runs once, even when the
client retries or two workers pick up the same request:

```python
from sagaz import SagaAlreadyExistsError

try:
    await OrderSaga(payments, inventory).run(order, saga_id=f"order-{order['order_id']}")
except SagaAlreadyExistsError as e:
    return {"status": e.status}   # it already ran (or is running): don't charge again
```

To run an id again on purpose, pass `allow_rerun=True`.

### One effect, one run

A saga id protects one request. Two *different* sagas can still call the same API that
is not idempotent: a checkout and a retry flow both charging order 42. Give such a step
an idempotency key, built from the saga context:

```python
@action("charge", idempotency_key="charge-{order_id}")   # or a function of the context
async def charge(self, ctx):
    return {"charge_id": await self.payments.charge(ctx["order_id"], ctx["amount"])}
```

A key runs once per tenant, across sagas of any class:

| The key | What the step does |
|---|---|
| Is new | Runs, and stores its result with the key |
| Already completed | Does not run: the stored result goes into the context, and the saga goes on. If this saga fails later, the step is compensated |
| Is held by a run that did not finish the step | Fails with `StepInDoubtError`, without running |

- **In doubt:** a key is left held when a process dies inside the step, the step is
  cancelled, or another saga is running it right now. The effect may or may not have
  happened, and sagaz does not guess: check it, then free the key in that tenant's scope
  with `await sagaz.release_step_key("charge-42", storage)`.
- **Freed keys:** a step that raises frees its key (it took no effect), and so does
  compensating the step, so a later run executes it again.
- **Where keys live:** in the saga storage, as reserved records, for as long as that
  storage lasts. The result must be JSON data.

## 4. When it fails

A failed run compensates what completed, in reverse order, and raises
`SagaFailedError`:

```python
from sagaz import SagaFailedError, SagaStatus

try:
    await OrderSaga(payments, inventory).run(order, saga_id=f"order-{order['order_id']}")
except SagaFailedError as e:
    log.warning("order failed at %s: %r", e.failed_step, e.__cause__)
    if e.status == SagaStatus.FAILED:          # a compensation failed too
        page_on_call(e.saga_id, e.compensation_errors)
    raise HTTPException(409, "order could not be completed") from e
```

For steps that cannot be undone (a payment captured, a parcel shipped), mark the step
`pivot=True`: once it completes, its ancestors are not compensated, and the saga only
moves forward. A saga that fails after its pivot reports `PARTIALLY_COMMITTED`, and a
`@forward_recovery` handler can retry or skip the failed step instead: see
[Pivots and forward recovery](pivots-and-forward-recovery.md).

### A deadline for the whole saga

Each step has a timeout. A deadline bounds all the steps together, so a caller that waits
30 seconds gets its answer within them:

```python
await OrderSaga(payments, inventory).run(order, deadline=30)   # seconds, or a timedelta

class OrderSaga(Saga):
    deadline = 30          # the default for every run; run(deadline=) overrides it
```

- **Past the deadline:** the steps still running are cancelled, and the saga fails as when
  a step fails. It compensates what completed and raises `SagaFailedError`, whose
  `__cause__` is a `SagaTimeoutError`.
- **Compensation is not bounded by it.** It runs to its end under its own timeouts, so a
  saga is never left half undone.
- **A cancelled step is not compensated,** because it did not complete. If it can leave an
  external effect half done, give the step its own shorter timeout, or an idempotency key
  (the key then stays held, in doubt, until you check).
- **Without one,** a saga has no time limit of its own, as before.

## 5. Test it without a database

Give each test its own config with in-memory storage, and inject fakes:

```python
import pytest

from sagaz import SagaConfig, SagaFailedError
from sagaz.core.storage import InMemorySagaStorage


class FakePayments:
    def __init__(self, decline=False):
        self.decline, self.refunds = decline, []

    async def charge(self, order_id, amount):
        if self.decline:
            raise ValueError("card declined")
        return "ch_1"

    async def refund(self, charge_id):
        self.refunds.append(charge_id)


class FakeInventory:
    def __init__(self):
        self.released = []

    async def reserve(self, items):
        return "r-1"

    async def release(self, reservation_id):
        self.released.append(reservation_id)


async def test_a_declined_card_releases_the_inventory():
    inventory = FakeInventory()
    config = SagaConfig(storage=InMemorySagaStorage(), metrics=False, logging=False)
    saga = OrderSaga(FakePayments(decline=True), inventory, config=config)

    with pytest.raises(SagaFailedError) as failure:
        await saga.run({"order_id": 1, "items": ["sku-1"], "amount": 10}, saga_id="o-1")

    assert failure.value.failed_step == "charge_payment"
    assert inventory.released == ["r-1"]
```

Set `max_retries=0` on steps (or `SagaConfig(default_max_retries=0)`) in tests that
fail on purpose, so they don't wait for retries.

## 6. Look a run up

```python
state = await config.storage.load_saga_state("order-42")
state["status"]                          # "completed", "rolled_back", "failed", ...
[(s["name"], s["status"], s["error"]) for s in state["steps"]]
```

From the shell:

```bash
sagaz saga show order-42 --storage-url postgresql://app@db/orders
```

## 7. Which feature do I need?

Most services need sections 1–6 and nothing else. Reach for the rest when the need
comes up:

| You need to… | Use | Guide |
|---|---|---|
| Publish events reliably when a saga's steps run | Transactional outbox and its worker | [Optimistic sending](../patterns/optimistic-sending.md) |
| Stream the outbox from the database log instead of polling | CDC (PostgreSQL logical replication, Debezium) | [CDC](../integrations/cdc.md) |
| Coordinate services by events, with no orchestrator | Choreography | [Choreography](../patterns/choreography.md) |
| Keep an audit trail of every event of a run | Event-sourced sagas | [Event sourcing](event-sourcing.md) |
| One log for orchestrated and choreographed sagas, for analytics | Unified saga log | [Unified saga log](unified-saga-log.md) |
| Isolate customers' sagas and data | Multi-tenancy | [Multi-tenancy](multi-tenancy.md) |
| Run steps in a specific region (data residency) | Multi-region | [Multi-region](multi-region.md) |
| Resume an interrupted compensation, see where each step is | Step charts | [Step charts](step-statechart.md) |
| Re-run a saga from a past point, for debugging | Snapshots and replay | [Saga replay](saga-replay.md) |
| Analytics over months of runs | Fluss and Iceberg lakehouse | [Lakehouse analytics](../monitoring/fluss-iceberg-analytics.md) |
