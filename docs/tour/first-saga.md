# Your first saga

An order needs stock reserved and a card charged. If the charge fails, the stock must be
released. A saga says that directly: each `@action` is a step, and the `@compensate`
with the same name undoes it.

```python title="first_saga.py"
--8<-- "docs/tour/code/first_saga.py"
```

It prints:

```text
--8<-- "docs/tour/code/first_saga.out"
```

What to notice:

- **A step returns a dict, and it is merged into the context.** `charge` reads
  `ctx["amount"]`; `release_stock` reads the `reservation` that `reserve_stock` returned.
- **`depends_on` orders the steps.** `charge` runs after `reserve_stock`.
- **A failed saga raises `SagaFailedError`,** after undoing what was done. Its `status`
  says how it ended (`rolled_back` here), `failed_step` where, and `__cause__` is your
  step's own exception.
- **The failed step is not compensated:** it did not complete. Only `reserve_stock` was undone.

## Without a class

The same saga, built step by step. Use it when the steps come from configuration, or
when you prefer functions.

```python title="imperative.py"
--8<-- "docs/tour/code/imperative.py"
```

It prints:

```text
--8<-- "docs/tour/code/imperative.out"
```

## Next

- [Parallel steps](parallel-steps.md): what happens without `depends_on`.
- [Your first saga service](../guides/first-saga-service.md): the same saga behind an HTTP endpoint, with a database.
