# Event Triggers & Auto-Discovery - Implementation Plan

**Status:** Proposed  
**Created:** 2026-01-07  
**Target Version:** v1.3.0  
**ADR:** [ADR-025: Event-Driven Triggers & Auto-Discovery](../adr/adr-025-event-driven-triggers.md)  
**Estimated Effort:** 2 weeks  

---

## Executive Summary

Implement an event-driven triggering system that allows Sagas to start automatically in response to external events (Kafka, Webhooks, Cron, etc.). This feature moves Sagaz from a purely imperative execution model ("run this saga") to a reactive one ("run when this happens").

---

## Goals

1.  **Reactive**: Sagas start automatically on events.
2.  **Auto-Discovery**: No manual registration; inheriting from `Saga` and using `@trigger` is enough.
3.  **Flexible**: One saga can respond to multiple triggers (Kafka + Webhook + Cron).
4.  **Integration-Ready**: Easy to trigger from FastAPI/Django/Flask.

---

## Technical Design

### 1. The `@trigger` Decorator

```python
# sagaz/triggers/decorators.py
def trigger(source: str, **kwargs):
    def decorator(func):
        func._trigger_metadata = TriggerMetadata(source=source, config=kwargs)
        return func
    return decorator
```

### 2. Trigger Registry

```python
# sagaz/triggers/registry.py
class TriggerRegistry:
    _registry = {}  # Map[SourceType, List[TriggerDefinition]]
    
    @classmethod
    def register(cls, saga_class, method_name, metadata):
        # ...
```

### 3. Saga Auto-Registration

```python
# sagaz/core.py
class Saga:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Scan methods for @trigger metadata
        # Register with TriggerRegistry
```

### 4. Event Processing Engine

```python
# sagaz/triggers/engine.py
class TriggerEngine:
    async def process_event(self, source: str, event_data: Any):
        # 1. Find matching triggers for source
        # 2. Execute trigger method (transformer) -> context
        # 3. If context returned, start Saga
```

---

## Implementation Phases

### Phase 1: Core Triggers (Week 1) - ✅ COMPLETED

*   [x] Create `sagaz.triggers` module structure.
*   [x] Implement `@trigger` decorator and `TriggerMetadata`.
*   [x] Implement `TriggerRegistry`.
*   [x] Update `Saga` class to auto-register triggers.
*   [x] Implement `TriggerEngine.fire()` (manual triggering).
*   [x] Unit tests for registration and manual firing.

### Phase 2: Orchestration & Concurrency (Week 1.5) - ✅ COMPLETED

*   [x] Implement concurrency controls (`max_concurrent`).
*   [x] Implement `idempotency_key` logic.
*   [x] Add persistence to declarative sagas (`decorators.Saga.run`).

### Phase 3: Sources & Integrations (Week 2) - ✅ COMPLETED

*   [x] **Cron Source**: `CronScheduler` for periodic saga triggering.
*   [x] **Webhook Integration**: FastAPI/Flask/Django webhook endpoints.
*   [x] **Broker Integration**: `BrokerTriggerConsumer` for message-driven triggers.

---

## Example Usage (Phase 1 Goal)

```python
class OrderSaga(Saga):
    @trigger(source="manual", event_type="order_created")
    def on_order(self, event):
        return {"order_id": event["id"]}

    @action("process")
    async def process(self, ctx):
        print(f"Processing order {ctx['order_id']}")

# In application code:
from sagaz.triggers import fire_event

# Fires the event -> TriggerEngine finds OrderSaga -> Helper runs on_order -> Saga starts
await fire_event("manual", {"event_type": "order_created", "id": "123"})
```
