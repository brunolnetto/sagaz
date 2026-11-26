# Examples

The [tour](../tour/index.md) shows one feature at a time, in scripts of twenty lines. The
examples here are whole scenarios: several features working together, the way a real
service would use them. Read the tour first if a word below is new.

## Walkthroughs

Two scenarios explained step by step, with the full source on the page.

| Walkthrough | Coordination | What it shows together |
|---|---|---|
| [Order fulfilment](order-fulfilment.md) | Choreography, four services | Events between services, compensation, a pivot, durable state, a tracker and a listener |
| [Cross-border wire transfer](wire-transfer.md) | Orchestrated saga, six steps | A chain of dependent steps, compensations, and a point of no return in the middle |

## Shipped examples

57 scenarios come with the package, from loan origination to smart-meter
deployment. [See the catalogue](shipped.md), or list them in your terminal:

```bash
sagaz examples list
sagaz examples run wire_transfer
```

## Which one should I read?

| If you are building... | Read |
|---|---|
| A workflow inside one service | [Cross-border wire transfer](wire-transfer.md) |
| A flow across several services | [Order fulfilment](order-fulfilment.md) |
| Something with a step that cannot be undone | Either walkthrough, then the examples marked **Pivot** in the [catalogue](shipped.md) |
| An HTTP service around a saga | `fastapi_app`, `flask_app` or `django_app` in the [catalogue](shipped.md), and [Your first saga service](../guides/first-saga-service.md) |
