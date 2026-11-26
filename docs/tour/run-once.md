# Running once

A customer double-clicks "pay". A client retries a request that had in fact succeeded.
Two protections keep an effect from happening twice.

```python title="run_once.py"
--8<-- "docs/tour/code/run_once.py"
```

It prints:

```text
--8<-- "docs/tour/code/run_once.out"
```

What to notice:

- **A saga id runs once.** Give `run()` a `saga_id` that identifies the business request
  (the checkout, the order): a second run with it is refused before any step runs.
- **A step key does its effect once, across sagas.** `idempotency_key="charge-{order_id}"`
  is filled from the context. Another saga that reaches the same key skips the step and
  gets the result the first one stored.
- **Both need a storage shared by your processes** to protect you in production. In this
  script the default in-memory storage is enough. See [Storage](storage.md).

## Next

- [Points of no return](pivots.md).
- [One effect, one run](../guides/first-saga-service.md#one-effect-one-run): keys per tenant, a step in doubt, and freeing a key.
