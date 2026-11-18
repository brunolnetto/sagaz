# Saga choreography

In **orchestration** (sagaz's `Saga`), one coordinator runs the steps and, on
failure, the compensations. In **choreography**, there is no coordinator: each
service reacts to events and publishes its own, and a failure makes every service
undo its part. Design: [ADR-029](../architecture/adr/adr-029-saga-choreography.md);
issue #56.

## Orchestration or choreography?

| | Orchestration (`Saga`) | Choreography (`ChoreographedSaga`) |
|---|---|---|
| Control flow | One place defines the order of steps | Emerges from which service reacts to which event |
| Coupling | The orchestrator knows every service | Services only know event types |
| Failure handling | The orchestrator runs compensations in reverse | Each service undoes its own actions when told to compensate |
| Visibility | The saga's state is one record | Reconstructed from events by a tracker |
| Adding a step | Change the saga definition | Add a service subscribed to an event |
| Good fit | A workflow owned by one team; strict ordering; easy reasoning | Independent services owned by different teams; high fan-out; loose coupling |

Start with orchestration. Choreography pays off when no single team should own the
whole flow, but it is harder to follow, so use the tracker.

## A choreographed order

```python
from sagaz.choreography import ChoreographedSaga, Event, compensate, on_event


class Inventory(ChoreographedSaga):
    @on_event("order.created")
    async def reserve(self, event: Event) -> None:
        await stock.reserve(event.data["order_id"])
        await self.emit("inventory.reserved", event.data)

    @compensate("order.created")
    async def release(self, event: Event) -> None:
        await stock.release(event.data["order_id"])


class Payments(ChoreographedSaga):
    @on_event("inventory.reserved")
    async def charge(self, event: Event) -> None:
        await gateway.charge(event.data["order_id"], event.data["amount"])  # may raise
        await self.emit("payment.charged", event.data)

    @compensate("inventory.reserved")
    async def refund(self, event: Event) -> None:
        await gateway.refund(event.data["order_id"])


class Shipping(ChoreographedSaga):
    @on_event("payment.charged")
    async def ship(self, event: Event) -> None:
        await self.emit("order.shipped", event.data)
```

Each service runs an engine on its bus:

```python
from sagaz.choreography import ChoreographyEngine, create_event_bus

bus = create_event_bus("kafka")            # or "redis" (Redis Streams), "rabbitmq", "memory"
engine = ChoreographyEngine(bus, completion_events={"order.shipped"})
engine.register(Inventory())
await bus.start()
await engine.start()
```

A transaction starts with `begin()`, which gives it a new correlation id:

```python
orders = ChoreographedSaga(name="orders")
engine.register(orders)
await orders.begin("order.created", {"order_id": "o-1", "amount": 40}, tenant_id="acme")
```

## What travels with an event

| Field | Set by | Meaning |
|---|---|---|
| `saga_id` / `correlation_id` | `begin()`, inherited by `emit()` | The business transaction |
| `tenant_id` | `begin()` (default: the current tenant scope), inherited | The tenant (ADR-020). Handlers run in that tenant's scope |
| `causation_id` | `emit()` | The `event_id` of the event being handled |
| `source` | `begin()` / `emit()` | The participant that published the event |

`emit()` only works inside a handler, because it continues that handler's
transaction. Use `begin()` to start one. Events published directly on the bus keep
whatever fields you set.

## Failure and compensation

When a handler raises, the engine publishes a `choreography.compensate` event with
the failing participant, the event it was handling and the reason. Every
participant receives it, runs its `@compensate` methods for the actions it
completed **in that transaction**, newest first, and reports with
`choreography.compensated`. The failed action itself is not compensated, because it
never completed.

An action counts as completed once its handler emits its result, or returns. Use
`completion_events` so that participants can forget a finished transaction. Each
participant also caps what it remembers (`max_tracked_transactions`, 10,000 by
default).

Once a participant has compensated a transaction, it ignores that transaction's
business events: they are counted with `outcome="after_compensation"` and logged, but
their handlers do not run. A late event can come from another partition, a
redelivery or a slow producer. Without this rule it would perform an action that
nothing will undo. With it, compensating before or after an event leads to the same
state: compensation is commutative, as distributed sagas require. Each participant
remembers its last `max_tracked_transactions` compensated transactions.

You can still model failures as domain events, for example a `payment.failed`
handled with `@on_event` as in ADR-029. The engine adds the generic path for
unexpected errors.

## Delivery guarantees

Buses deliver at least once, so the engine drops a second delivery of the same
`event_id` to the same participant (bounded memory, 100,000 deliveries by default).
Handlers that call external systems should still be idempotent. The idempotency only
holds for the lifetime of the process.

Within one transaction, the buses deliver events in the order they were published:

| Bus | Ordering |
|---|---|
| Kafka | Per transaction. Events are keyed by correlation id, so a transaction's events share a partition. Events without one are keyed by type. |
| Redis Streams | Per stream: the whole topic is one ordered stream. |
| RabbitMQ | Per queue, with a single consumer per queue. |
| In-memory | Nested and depth-first: an event published by a handler is delivered before the handler returns. |

There is no ordering between different transactions. Participants still handle a
`choreography.compensate` that overtakes a business event correctly (see above).

This memory, like deduplication, lives in the process. A participant that restarts
forgets what it has to compensate (#448).

## Status of a transaction

`ChoreographyTracker` subscribes to every event and builds each transaction's status
from the events alone:

| Status | Meaning |
|---|---|
| `executing` | Events seen, no failure, no completion event yet |
| `completed` | A completion event was seen |
| `compensating` | A participant failed; not every participant that emitted events has reported compensation |
| `compensated` | Every participant that emitted events (other than the failed one) reported compensation |
| `failed` | A compensation itself raised |

The status does not depend on the order events arrive in. Run **one** tracker with a
saga storage so that other processes can read it:

```python
from sagaz.choreography import ChoreographyTracker

tracker = ChoreographyTracker(bus, storage=saga_storage, completion_events={"order.shipped"})
await tracker.start()
```

```bash
sagaz choreography status <correlation-id> --tenant acme --storage-url postgresql://...
sagaz choreography status <correlation-id> --events      # every event seen
sagaz choreography status <correlation-id> --json
```

## Metrics

| Metric | Labels |
|---|---|
| `sagaz_choreography_events_total` | `participant`, `event_type`, `outcome` (`handled`, `failed`, `duplicate`, `after_compensation`) |
| `sagaz_choreography_handler_seconds` | `participant`, `event_type` |
| `sagaz_choreography_compensations_total` | `participant`, `outcome` (`undone`, `failed`) |

## Performance

With the in-memory bus on a laptop, the engine dispatched about 24,800 events/s with
a p99 of 0.07 ms per delivery, including deduplication, tenant scoping and metrics
(`tests/integration/test_choreography_performance.py`, marker `performance`). Over a
real broker, the broker's own latency dominates.
