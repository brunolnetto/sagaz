# sagaz

**Business transactions that span several steps or services, and undo themselves when one fails.**

A *saga* is a transaction made of steps, where each step knows how to undo itself. When
a step fails, sagaz undoes the ones already done, in reverse order, and tells you how it
ended. You write the steps; sagaz does the bookkeeping: ordering, retries, timeouts,
compensation, persistence, and telling apart "everything was undone" from "someone must
look at this".

```bash
pip install sagaz
```

## A saga in thirty lines

```python title="first_saga.py"
"""A saga: steps that each know how to undo themselves."""

import asyncio

from sagaz import Saga, SagaFailedError, action, compensate


class OrderSaga(Saga):
    saga_name = "order"

    @action("reserve_stock")
    async def reserve_stock(self, ctx):
        print("reserving stock for", ctx["order_id"])
        return {"reservation": "r-1"}  # merged into the context

    @compensate("reserve_stock")
    async def release_stock(self, ctx):
        print("releasing", ctx["reservation"])

    @action("charge", depends_on=["reserve_stock"])
    async def charge(self, ctx):
        if ctx["amount"] > 100:
            raise ValueError("card declined")
        print("charging", ctx["amount"])
        return {"payment": "p-1"}

    @compensate("charge")
    async def refund(self, ctx):
        print("refunding", ctx["payment"])


async def main():
    result = await OrderSaga().run({"order_id": "o-1", "amount": 40})
    print("done:", result["reservation"], result["payment"])

    print("--- an order that fails ---")
    try:
        await OrderSaga().run({"order_id": "o-2", "amount": 500})
    except SagaFailedError as failure:
        print("failed at", failure.failed_step, "->", failure.status.value)


asyncio.run(main())
```

Run it with `python first_saga.py`:

```text
reserving stock for o-1
charging 40
done: r-1 p-1
--- an order that fails ---
reserving stock for o-2
releasing r-1
failed at charge -> rolled_back
```

The second order's card is declined, so sagaz releases the stock it had reserved and
raises `SagaFailedError`. [The tour explains it line by line](tour/first-saga.md).

## Two ways to coordinate

| | Orchestrated saga | Choreographed saga |
|---|---|---|
| **Who knows the steps** | One saga object | Nobody: each service reacts to events |
| **Fits** | A workflow inside one service | A flow across services that should not know each other |
| **Start with** | [Your first saga](tour/first-saga.md) | [Your first choreography](tour/choreography.md) |

Both offer the same capabilities: retries and timeouts, running once, deadlines, points
of no return, listeners, tenants, diagrams. The [feature matrix](reference/feature-matrix.md)
lists them side by side.

## Where to go

<div class="grid cards" markdown>

- **[Tour](tour/index.md)**

    One feature per page, each with a script of about twenty lines that runs as shown.
    Start here.

- **[Examples](examples/index.md)**

    Whole scenarios: two explained step by step, and 57 shipped with the package.

- **[Guides](guides/first-saga-service.md)**

    How to do one thing well: a saga behind an HTTP endpoint, configuration, multi-tenancy,
    replay, deployment.

- **[Reference](reference/feature-matrix.md)**

    Every feature by coordination style, the configuration, the metrics.

</div>

## What is in the box

- **Steps and compensation,** declared with decorators or added one by one.
- **Parallel steps** from their dependencies, with a choice of what to do when one fails.
- **Retries, timeouts and deadlines.**
- **Run-once** saga ids and per-step idempotency keys.
- **Points of no return** and forward recovery.
- **Choreography** on an in-process bus, Kafka, RabbitMQ or Redis Streams, with compensation, pivots and diagrams.
- **Storage** in memory, SQLite, PostgreSQL or Redis; a transactional outbox; event sourcing and replay.
- **Observability:** listeners, Prometheus metrics, OpenTelemetry tracing, ready-made alerts and dashboards.
- **Multi-tenancy,** a CLI, Kubernetes manifests and a Helm chart.

## Project

- Source and issues: [github.com/brunolnetto/sagaz](https://github.com/brunolnetto/sagaz)
- Package: [pypi.org/project/sagaz](https://pypi.org/project/sagaz/)
- [Changelog](development/changelog.md) · [Roadmap](ROADMAP.md) · [Contributing](development/contributing.md)
