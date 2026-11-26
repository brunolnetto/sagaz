# Retries, timeouts and deadlines

Networks fail for a moment and come back. A step can be tried again before the saga
gives up, each attempt can have a time limit, and the saga as a whole can have a deadline.

```python title="retries.py"
--8<-- "docs/tour/code/retries.py"
```

It prints:

```text
--8<-- "docs/tour/code/retries.out"
```

What to notice:

- **`max_retries=3`** means up to four attempts. Between attempts sagaz waits a little
  longer each time.
- **`timeout_seconds`** limits one attempt. A timed-out attempt is retried like a failed one.
- **`deadline=`** limits all the steps together. When it passes, the saga stops, undoes
  what it did and raises `SagaFailedError` caused by a `SagaTimeoutError`. The
  compensations are not cut short by the deadline.
- **Retried steps should be safe to repeat.** If a step might have charged the card
  before failing, see [Running once](run-once.md).

## Next

- [Running once](run-once.md).
- [Configuration](../guides/configuration.md): defaults for every saga (`default_max_retries`, `default_timeout`).
