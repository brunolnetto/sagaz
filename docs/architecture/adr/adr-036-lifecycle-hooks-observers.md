# ADR-036: Saga Lifecycle Hooks & Observers

## Status

**Accepted** — ✅ **FULLY IMPLEMENTED** (v1.3.0)

## Context

As sagas execute, a range of cross-cutting concerns must observe and react to
step lifecycle events: structured logging, Prometheus metrics emission, outbox
event publishing, distributed trace propagation, and custom alerting.

The initial implementation addressed these concerns through a combination of
scattered decorator logic and ad-hoc callbacks, leading to:

| Problem | Impact |
|---------|--------|
| Duplicated observability code per saga | Hard to enforce consistency |
| No standard extension point | Users had to fork internals to add custom behaviour |
| Tight coupling between step logic and instrumentation | Made unit testing harder |
| No ordering guarantee for multiple observers | Unpredictable cross-cutting behaviour |

Two complementary mechanisms were evaluated:

1. **Decorator-based hooks** — fine-grained, per-step callbacks attached at
   definition time via the `@step` decorator.  
2. **Class-based listeners** — coarse-grained, saga-level observers registered
   via a `listeners` attribute on the saga class.

## Decision

Implement **both** mechanisms with distinct scopes to cover different use cases:

### 1. Per-Step Hooks (`sagaz/core/hooks.py`)

Hooks are async (or sync) callables attached to individual steps via the
`@step` decorator:

```python
@step(
    "charge_payment",
    on_success=publish_on_success(storage, "payment.charged"),
    on_failure=publish_on_failure(storage, "payment.failed"),
    on_enter=log_step_enter,
    on_exit=log_step_exit,
)
async def charge_payment(self, ctx: SagaContext) -> dict:
    ...
```

Provided factory functions in `sagaz.core.hooks`:

| Factory | Trigger | Effect |
|---------|---------|--------|
| `publish_on_success` | Step succeeds | Publish event to transactional outbox |
| `publish_on_failure` | Step fails | Publish failure event to outbox |
| `on_step_enter` | Step starts | Decorator-marker for documentation/IDE support |
| `on_step_exit` | Step finishes | Decorator-marker for documentation/IDE support |

### 2. Saga-Level Listeners (`sagaz/core/listeners.py`)

Listeners implement the **Observer pattern** via a base class registered at
the saga class level.  Every event on every step is dispatched to all
registered listeners in insertion order.

```python
class OrderSaga(Saga):
    listeners = [MetricsSagaListener(), LoggingSagaListener()]
```

Built-in listeners shipped in `sagaz.core.listeners`:

| Listener | Behaviour |
|----------|-----------|
| `LoggingSagaListener` | Structured JSON log for each lifecycle event |
| `MetricsSagaListener` | Prometheus counter/histogram increments |

The `SagaListener` ABC defines eight optional async callbacks:

```
on_saga_start        → saga begins
on_step_enter        → before each step
on_step_success      → step succeeded
on_step_failure      → step raised an exception
on_compensation_start     → before compensation runs
on_compensation_complete  → after compensation completes
on_saga_complete     → saga finished successfully
on_saga_failed       → saga failed (all compensations attempted)
```

All methods default to no-ops, so subclasses only override what they need.

### Error Isolation

Listener errors are caught, logged, and silently swallowed — a misbehaving
observer never prevents saga execution.

## Alternatives Considered

### A: Event Bus / Message-Passing

Route lifecycle events through an internal event bus (similar to Spring
Application Events). Rejected: adds a runtime dependency and increases latency
with no benefit at the scale of a single process.

### B: Middleware Stack (like WSGI middleware)

Wrap step execution in a middleware chain. Rejected: the chain model is less
discoverable and harder to reorder without touching every step definition.

### C: Hooks Only (No Listeners)

Per-step hooks are more explicit but require every step to be individually
annotated. For saga-wide concerns (logging, metrics), this leads to identical
boilerplate on every `@step`. The dual mechanism keeps per-step precision
available while providing saga-wide convenience.

## Consequences

### Positive

- Common observability concerns (logging, metrics, tracing) are zero-effort for
  end users via the built-in listeners.
- Custom behaviour is additive without modifying saga internals.
- Both mechanisms are independently testable.
- Listener ordering is deterministic (list index).
- Listener errors never corrupt saga state.

### Negative

- Two overlapping extension points may confuse new contributors; documentation
  must be clear about when to use which.
- Synchronous listener implementations are supported but may inadvertently block
  the event loop; documentation warns against blocking I/O in listeners.

## Implementation Reference

| File | Purpose |
|------|---------|
| `sagaz/core/hooks.py` | Hook factory functions and decorator helpers |
| `sagaz/core/listeners.py` | `SagaListener` ABC + built-in implementations |
| `sagaz/core/saga.py` | Dispatch calls to registered listeners |
| `sagaz/core/decorators.py` | `@step` decorator wires hooks to step wrappers |

## Links

- [ADR-012: Synchronous Orchestration Model](adr-012-synchronous-orchestration-model.md)
- [ADR-025: Event-Driven Triggers](adr-025-event-driven-triggers.md)
- [Hooks Guide](../../guides/)
