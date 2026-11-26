# Points of no return

Some steps cannot be undone: a card charged, a parcel handed to a carrier. Mark such a
step `pivot=True`. Before it, a failed saga rolls back. After it, the saga can only move
forward, and a `@forward_recovery` handler decides how.

```python title="pivot.py"
--8<-- "docs/tour/code/pivot.py"
```

It prints:

```text
--8<-- "docs/tour/code/pivot.out"
```

What to notice:

- **First run:** shipping fails, the handler picks another carrier, the step runs again
  and the saga completes.
- **Second run:** the handler cannot fix it and asks for a person. Nothing is undone:
  the stock stays reserved, because releasing it would contradict a charge that stands.
  The saga ends in `forward_recovery`.
- **Without a handler,** a saga that fails after its pivot undoes what is still
  reversible and ends `partially_committed`.

Either status means someone must act. sagaz ships an alert for it:
[sagas that need a person](../monitoring/alerting.md#sagas-that-need-a-person).

## Next

- [Pivots and forward recovery](../guides/pivots-and-forward-recovery.md): every recovery action and every status.
- [Listeners](listeners.md).
