# Storage

Until now each saga lived in memory. Give sagaz a storage, and every saga's state is
written as it runs: you can look a saga up later, from another process, and the
protections of [Running once](run-once.md) hold across your whole service.

```python title="storage.py"
--8<-- "docs/tour/code/storage.py"
```

It prints:

```text
--8<-- "docs/tour/code/storage.out"
```

What to notice:

- **`SagaConfig(storage=...)`** is all a saga needs. To set it once for every saga, call
  `sagaz.configure(SagaConfig(...))` when your application starts.
- **The state has every step's status:** the failed order shows `charge` failed and
  `reserve` compensated.
- **SQLite is for one machine.** PostgreSQL and Redis storages have the same interface.

## Next

- [Configuration](../guides/configuration.md): storages, brokers and environment variables.
- [Unified saga log](../guides/unified-saga-log.md): state, events and outbox in one transaction.
- [Saga replay](../guides/saga-replay.md): snapshots, and running a saga again from a step.
- [Your first choreography](choreography.md).
