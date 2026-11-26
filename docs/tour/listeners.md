# Listeners

You want a log line for every step, a metric for every failure, an audit trail. A
listener receives what happens in a saga, so the steps stay about the business.

```python title="listeners.py"
--8<-- "docs/tour/code/listeners.py"
```

It prints:

```text
--8<-- "docs/tour/code/listeners.out"
```

What to notice:

- **Override only the hooks you need.** There is one for the saga starting, completing
  and failing, and one for each step and each compensation.
- **A listener cannot break a saga.** One that raises is logged and skipped; a slow one
  is cut off after 5 seconds.
- **sagaz ships listeners** for logging (`LoggingSagaListener`), Prometheus metrics
  (`MetricsSagaListener`), tracing (`TracingSagaListener`) and the transactional outbox
  (`OutboxSagaListener`).

## Next

- [Storage](storage.md).
- [Observability reference](../monitoring/OBSERVABILITY_REFERENCE.md): every metric and span.
- [Alerting](../monitoring/alerting.md): ready-made Prometheus alert rules.
