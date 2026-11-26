# Your first choreography

In a choreography there is no saga object that knows every step. Each service is a
**participant**: it handles the events it cares about and publishes its own. The
business transaction is the chain of events.

```python title="choreography.py"
--8<-- "docs/tour/code/choreography.py"
```

It prints:

```text
--8<-- "docs/tour/code/choreography.out"
```

What to notice:

- **`@on_event` handles an event type;** `self.emit(...)` publishes the next one, in the
  same transaction.
- **`begin()` starts a transaction.** Every event that follows carries its correlation id.
- **The participants do not know each other.** `Inventory` never mentions `Shipping`.
- **The bus here is in memory.** In production each service has its own engine on a
  shared Kafka, RabbitMQ or Redis Streams bus; the participants do not change.

## When a participant fails

There is no central saga to undo things, so the engine publishes a request to
compensate, and every participant undoes what it did in that transaction.

```python title="choreography_compensation.py"
--8<-- "docs/tour/code/choreography_compensation.py"
```

It prints:

```text
--8<-- "docs/tour/code/choreography_compensation.out"
```

What to notice:

- **`@compensate("order.created")`** undoes the action taken on that event.
- **The second order:** the charge fails, and `inventory` releases its reservation.
- **A `ChoreographyTracker` watches every event** and tells the status of a transaction,
  the one thing no single participant can know.
- **Handlers are retried by default** (3 times), like orchestrated steps. The example
  sets `max_retries=0` to fail at once.

## Next

- [Pivots and diagrams](choreography-pivots-and-diagrams.md).
- [Saga choreography](../patterns/choreography.md): delivery guarantees, deadlines, tenants, durable state.
