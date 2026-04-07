# ADR-033: Event Sourcing Integration

## Status

**Proposed** | Date: 2026-04-07 | Priority: Medium | Target: v2.3.0

**Implementation Status:**
- ⚪ Phase 1: Event Store Infrastructure (Not Started)
- ⚪ Phase 2: Saga State as Events (Not Started)
- ⚪ Phase 3: Projection & Read-Model Builder (Not Started)
- ⚪ Phase 4: Snapshot Strategy (Not Started)
- ⚪ Phase 5: CLI & Observability (Not Started)

## Dependencies

**Prerequisites**:
- ADR-016: Unified Storage Layer (event store built on top of unified storage)
- ADR-024: Saga Replay & Time-Travel (replay uses event log as source of truth)

**Synergies** (Optional):
- ADR-013: Fluss Analytics (event streams ingested into Fluss for real-time analytics)
- ADR-029: Saga Choreography (choreography naturally produces events; event sourcing stores them)
- ADR-025: Event-Driven Triggers (triggers subscribe to projections)

**Roadmap**: **Phase 7 (v2.3.0)** — Advanced state management

## Context

Sagaz currently uses a **state snapshot model**: each saga persists its current state as a single row in the storage backend. This approach is simple but has limitations:

### Current State Snapshot Model

```
saga_snapshots table
┌────────────────────────────────────────────┐
│ saga_id │ status │ current_step │ context  │
│ ..data.. │ EXEC   │ step_3       │ {..}     │  ← Only CURRENT state
└────────────────────────────────────────────┘
```

### Problems with Snapshots Only

| Problem | Impact |
|---------|--------|
| No history of how state changed | Debugging requires log correlation |
| Audit trail is incomplete | Compliance gaps for regulated industries |
| Replay needs external log | ADR-024 adds log as separate concern |
| Temporal queries are approximate | Time-travel relies on created_at timestamps |
| Schema migrations are destructive | Changing context shape loses history |

### Event Sourcing Model

Instead of storing the *current state*, store the *sequence of events* that led to that state. State is derived by replaying events.

```
saga_events table
┌──────────────────────────────────────────────────────────────────┐
│ event_id │ saga_id │ event_type          │ payload   │ occurred_at │
│ 1        │ abc-123 │ SagaStarted         │ {..}      │ 12:00:00   │
│ 2        │ abc-123 │ StepExecuted        │ {step_1}  │ 12:00:01   │
│ 3        │ abc-123 │ StepExecuted        │ {step_2}  │ 12:00:02   │
│ 4        │ abc-123 │ StepFailed          │ {step_3}  │ 12:00:03   │
│ 5        │ abc-123 │ CompensationStarted │ {..}      │ 12:00:04   │
│ 6        │ abc-123 │ StepCompensated     │ {step_2}  │ 12:00:05   │
│ 7        │ abc-123 │ SagaRolledBack      │ {..}      │ 12:00:06   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Decision

Implement **Event Sourcing** as an opt-in storage strategy so that saga state changes are persisted as an immutable, append-only sequence of domain events. Snapshots are kept as a performance optimisation over long event streams.

### Design Principles

1. **Opt-in**: Default storage mode remains snapshot-based; event sourcing is enabled per-saga via config.
2. **Append-only**: Events are never updated or deleted. Snapshots are derived artefacts.
3. **Domain events only**: Only saga lifecycle events are stored (not infrastructure noise).
4. **Backward compatible**: Existing snapshot-based sagas continue to work unchanged.
5. **Snapshot threshold**: After `N` events (configurable, default: 50), a snapshot is written to avoid full replay on every load.

---

## Proposed Architecture

### Event Types

```python
# sagaz/core/events.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass(frozen=True)
class SagaEvent:
    event_id: str
    saga_id: str
    saga_class: str
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class SagaStarted(SagaEvent): ...

@dataclass(frozen=True)
class StepExecuted(SagaEvent):
    step_name: str = ""

@dataclass(frozen=True)
class StepFailed(SagaEvent):
    step_name: str = ""
    error: str = ""

@dataclass(frozen=True)
class StepCompensated(SagaEvent):
    step_name: str = ""

@dataclass(frozen=True)
class CompensationStarted(SagaEvent): ...

@dataclass(frozen=True)
class SagaCompleted(SagaEvent): ...

@dataclass(frozen=True)
class SagaRolledBack(SagaEvent): ...

@dataclass(frozen=True)
class SagaFailed(SagaEvent):
    reason: str = ""
```

### Event Store Interface

```python
# sagaz/storage/event_store.py
from abc import ABC, abstractmethod

class SagaEventStore(ABC):
    @abstractmethod
    async def append(self, event: SagaEvent) -> None:
        """Append a new event to the stream for saga_id."""

    @abstractmethod
    async def load_stream(self, saga_id: str) -> list[SagaEvent]:
        """Load all events for a saga in order."""

    @abstractmethod
    async def load_stream_after(self, saga_id: str, after_sequence: int) -> list[SagaEvent]:
        """Load events after a given sequence number (for incremental replay)."""

    @abstractmethod
    async def save_snapshot(self, saga_id: str, sequence: int, state: dict) -> None:
        """Save a snapshot at the given sequence number."""

    @abstractmethod
    async def load_latest_snapshot(self, saga_id: str) -> tuple[int, dict] | None:
        """Return (sequence, state) of the latest snapshot, or None."""
```

### Opt-in Configuration

```python
class MySaga(Saga):
    class Meta:
        storage_strategy = "event_sourced"   # or "snapshot" (default)
        snapshot_threshold = 25              # snapshot every 25 events
```

### Projection / Read-Model

```python
# sagaz/projections/saga_summary.py
class SagaSummaryProjection:
    """Builds a summary read-model from the event stream."""

    async def apply(self, event: SagaEvent) -> None:
        match event:
            case SagaStarted():  self._on_started(event)
            case StepExecuted(): self._on_step_executed(event)
            case SagaCompleted(): self._on_completed(event)
            case SagaRolledBack(): self._on_rolled_back(event)
```

---

## Implementation Phases

### Phase 1: Event Store Infrastructure (2 weeks)
- Define `SagaEvent` hierarchy in `sagaz/core/events.py`
- `SagaEventStore` abstract interface in `sagaz/storage/event_store.py`
- PostgreSQL backend: `saga_events` table with `saga_id`, `sequence`, `event_type`, `payload`, `occurred_at`
- SQLite backend (for dev/test)

### Phase 2: Saga State as Events (1 week)
- Instrument `Saga` and `DAGSaga` to emit events at each lifecycle transition
- `EventSourcedSagaStorage` wraps the event store; `save` appends an event; `load` replays events
- `Meta.storage_strategy = "event_sourced"` wires the new storage

### Phase 3: Projection & Read-Model Builder (1 week)
- `SagaSummaryProjection` — fastest-path read model (replaces raw snapshot for queries)
- `ProjectionRunner` subscribes to event store and updates projections asynchronously
- `sagaz/projections/` directory with built-in projections

### Phase 4: Snapshot Strategy (1 week)
- Write snapshot after every N events (`snapshot_threshold`)
- `load` uses latest snapshot + tail events for O(tail) instead of O(all) replay

### Phase 5: CLI & Observability (0.5 weeks)
- `sagaz event-log <saga-id>` — pretty-print the full event stream for a saga
- Prometheus metric: `sagaz_event_store_events_total`
- Grafana panel: event rate per saga class

---

## Consequences

### Positive
- Full audit trail for every saga — satisfies GDPR, HIPAA, PCI-DSS requirements
- Replay (ADR-024) becomes trivial: just replay the event stream
- Time-travel queries are exact, not approximate
- Schema migration is non-destructive (old events keep old schema; new events use new schema)

### Negative
- Increased storage footprint (all events retained)
- Read latency increases for long-lived sagas without snapshots
- More complex testing (projections need their own tests)

### Mitigation
- Snapshot threshold keeps replay fast
- TTL-based archival moves old events to cold storage (Iceberg, S3)
- Event schema versioning via `event_version` field

---

## Acceptance Criteria

- [ ] `SagaEvent` hierarchy implemented in `sagaz/core/events.py`
- [ ] `SagaEventStore` interface in `sagaz/storage/event_store.py`
- [ ] PostgreSQL backend: `saga_events` table + `EventSourcedSagaStorage`
- [ ] SQLite backend: same interface for dev/test
- [ ] `Saga.Meta.storage_strategy = "event_sourced"` opt-in works
- [ ] Snapshot-on-threshold implemented; load uses snapshot + tail
- [ ] `SagaSummaryProjection` implemented and tested
- [ ] `sagaz event-log <saga-id>` CLI command
- [ ] Prometheus metric + Grafana panel
- [ ] 90%+ coverage for new code
- [ ] Integration test: 100 saga lifecycle events → projection is consistent

## Rejected Alternatives

### Always-on Event Sourcing
Rejected because it would be a breaking change for all existing deployments. Opt-in is safer.

### External Event Store (EventStoreDB, Axon)
Rejected to avoid adding another infrastructure dependency. Sagaz's own storage backends are sufficient for the target use cases.
