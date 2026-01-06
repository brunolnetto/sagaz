# Architecture Decision Records

This document captures key architectural decisions and their rationale.

---

## ADR-001: Transactional Outbox Pattern

### Context

We need to ensure events are published reliably after saga steps complete, without distributed transaction coordination.

### Decision

Use the **Transactional Outbox Pattern**:
- Store events in the same database transaction as business data
- Separate worker polls and publishes events asynchronously

### Consequences

✅ **Pros:**
- Atomic: business data and events are consistent
- No distributed transactions needed
- Events survive application crashes

❌ **Cons:**
- At-least-once delivery (need consumer idempotency)
- Adds latency (async publishing)
- Requires polling (or CDC)

---

## ADR-002: FOR UPDATE SKIP LOCKED for Concurrency

### Context

Multiple workers need to process events without duplicating work.

### Decision

Use PostgreSQL's `FOR UPDATE SKIP LOCKED`:

```sql
SELECT * FROM saga_outbox
WHERE status = 'pending'
LIMIT 100
FOR UPDATE SKIP LOCKED
```

### Consequences

✅ **Pros:**
- No explicit distributed locks needed
- Workers never block each other
- PostgreSQL handles concurrency

❌ **Cons:**
- PostgreSQL-specific (not portable)
- High contention at scale (many workers, few events)

---

## ADR-003: Worker-based Publishing vs CDC

### Context

Two approaches to publish outbox events:
1. **Polling workers** - periodically query pending events
2. **CDC (Change Data Capture)** - stream DB changes via Debezium

### Decision

Use **polling workers** for simplicity.

### Rationale

| Factor | Polling | CDC |
|--------|---------|-----|
| Setup complexity | Low | High (Kafka Connect, Debezium) |
| Latency | Configurable (1s default) | Near real-time |
| Operational burden | Low | High |
| Throughput | 1-5K/sec | 10K+/sec |

### When to Switch to CDC

- Throughput > 5K events/sec needed
- Sub-100ms latency required
- Team has Kafka/Debezium expertise

---

## ADR-004: Consumer Inbox for Idempotency

### Context

With at-least-once delivery, consumers may receive duplicates.

### Decision

Implement **Consumer Inbox Pattern**:
- Store `event_id` in `consumer_inbox` table within consumer's transaction
- Check before processing; skip if already exists

### Consequences

✅ **Pros:**
- True exactly-once processing semantics
- Works with any broker

❌ **Cons:**
- Requires database on consumer side
- Slight performance overhead

---

## ADR-005: Saga Compensation Order

### Context

When a saga fails, compensations must run. Two approaches:
1. **Reverse order** - compensate in LIFO order
2. **Dependency graph** - compensate based on dependencies

### Decision

Support **both**:
- Default: reverse order (simple, predictable)
- Optional: `CompensationGraph` for complex dependencies

### Example

```python
# Default: reverse order
saga.step("A").step("B").step("C")
# If C fails: compensate B, then A

# With graph: parallel + dependencies
graph = CompensationGraph()
graph.add_node("A", comp_a)
graph.add_node("B", comp_b)
graph.add_node("C", comp_c, depends_on=["A", "B"])
# Compensates A and B in parallel, then C
```

---

## ADR-006: Async-First Design

### Context

Modern Python applications are increasingly async for I/O concurrency.

### Decision

Make all public APIs **async-first**.

### Consequences

✅ **Pros:**
- Natural fit for I/O-bound saga steps
- Efficient worker polling
- Compatible with FastAPI, aiohttp, etc.

❌ **Cons:**
- Requires `asyncio` knowledge
- Sync users must wrap with `asyncio.run()`

---

## ADR-007: Pluggable Storage and Brokers

### Context

Different organizations use different infrastructure.

### Decision

Define **abstract base classes** for storage and brokers:

```python
class OutboxStorage(ABC):
    async def save_event(self, event): ...
    async def claim_batch(self, worker_id, size): ...

class MessageBroker(ABC):
    async def publish_event(self, event): ...
```

### Implementations

| Storage | Broker |
|---------|--------|
| PostgreSQL | RabbitMQ |
| In-Memory (testing) | Kafka |
| | In-Memory (testing) |

---

## ADR-008: JSON Payloads

### Context

Events need a serialization format.

### Decision

Use **JSON** for event payloads, stored as `JSONB` in PostgreSQL.

### Rationale

- Human-readable for debugging
- Native PostgreSQL indexing support
- Universal compatibility
- Schema evolution via JSON Schema (optional)

---

## ADR-009: Stateless Workers

### Context

Workers need to scale horizontally.

### Decision

Workers are **completely stateless**:
- No local caches
- Worker ID from environment/pod name
- All state in PostgreSQL

### Consequences

✅ **Pros:**
- Easy horizontal scaling
- Pod restarts are safe
- No coordination needed

---

## ADR-010: Dead Letter Queue

### Context

Some events may never succeed (bad data, downstream unavailable forever).

### Decision

After `max_retries` failures, move events to `DEAD_LETTER` status.

### Handling

1. Events stay in same table with `status = 'dead_letter'`
2. Alerting via Prometheus metrics
3. Manual review and replay via admin tooling

---

## ADR-011: CDC (Change Data Capture) Support

### Context

For high-throughput requirements (50K+ events/sec), polling-based workers have limitations.

### Decision

Design CDC support as an **optional upgrade path** using Debezium.

### Status

**Proposed** - See [ADR-011: CDC Support](adr/adr-011-cdc-support.md) for full design.

---

## ADR-012: Synchronous Orchestration Model

### Context

Saga patterns can be implemented with synchronous (direct function calls) or distributed (message-based) orchestration.

### Decision

Sagaz v1.0 uses **synchronous orchestration**:
- Steps execute as direct `await` calls within a single process
- `SagaListener` provides lifecycle hooks for observability, not message consumption
- Outbox pattern is for downstream notifications, not saga flow control

### Rationale

- Simpler debugging (stack traces, local variables)
- Lower latency (no message broker hops between steps)
- Easier testing (mock functions, not brokers)
- Fits the primary use case: coordinating multiple operations within one service

### Status

**Accepted** - See [ADR-012: Synchronous Orchestration Model](adr/adr-012-synchronous-orchestration-model.md) for details.

For distributed saga support (steps as separate services), see [Design Doc: Distributed Saga Support](design-distributed-saga-support.md).

---

## ADR-016: Unified Storage Layer

### Context

Sagaz has two separate storage hierarchies (saga storage and outbox storage) with significant code duplication and inconsistent feature coverage (e.g., Redis has no outbox storage).

### Decision

Unify the storage layer with:
- Shared core infrastructure (`storage/core/`)
- Complete backend coverage (add Redis outbox, SQLite)
- Data transfer layer for migrations
- Unified factory API
- Backward compatibility layer

### Rationale

- Eliminates ~200 lines of duplicated code
- Enables Redis as full backend (saga + outbox)
- Allows data migration between backends
- Simplifies API and maintenance

### Status

**Accepted** - See [ADR-016: Unified Storage Layer](adr/adr-016-unified-storage-layer.md) for details.

Implementation plan: [Unified Storage Implementation Plan](implementation-plans/unified-storage-implementation-plan.md)

---

## ADR-023: Pivot/Irreversible Steps

### Context

Certain operations in distributed systems represent a **point of no return** where compensation is impossible (e.g., payment capture, physical shipments, external API calls with irreversible side effects).

### Decision

Introduce **pivot steps** with taint propagation and forward recovery:
- `pivot=True` marks point-of-no-return steps
- `@forward_recovery("step_name")` defines how to recover forward when downstream fails
- Executed pivots taint all ancestor steps (making them non-compensable)
- Parallel branches without pivots remain compensable

### Rationale

- Real-world workflows include irreversible operations
- Forward recovery provides explicit path when compensation is impossible
- Tainting logic prevents invalid compensation attempts
- Visualization shows recovery paths clearly

### Status

**Proposed** - See [ADR-023: Pivot/Irreversible Steps](adr/adr-023-pivot-irreversible-steps.md) for comprehensive design.

---

## ADR-025: Event-Driven Triggers & Auto-Discovery

### Context

Current imperative execution (`saga.run()`) creates friction for event-driven architectures and streaming MLOps, requiring manual boilerplate to wire events to sagas.

### Decision

Implement **Event-Driven Triggers** with auto-discovery:
- `@trigger(source, topic)` decorator to map events to saga contexts
- **Auto-Discovery**: Sagas are automatically registered upon import via `__init_subclass__`
- **Unified Action**: `@action` execution mode (sync vs streaming) determined by return type (generator vs value)

### Rationale

- **Zero Boilerplate**: Import-based discovery reduces setup code
- **Reactive**: Sagas become first-class consumers of events
- **Unified API**: No need for separate `@streaming_action`

### Status

**Proposed** - See [ADR-025: Event-Driven Triggers](adr/adr-025-event-driven-triggers.md) for details.

---

## Summary

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Transactional Outbox | Reliable events without distributed TX |
| 2 | SKIP LOCKED | Safe concurrent processing |
| 3 | Polling vs CDC | Simplicity over raw throughput |
| 4 | Consumer Inbox | Exactly-once semantics |
| 5 | Flexible Compensation | Simple default, complex optional |
| 6 | Async-First | Modern Python patterns |
| 7 | Pluggable Backends | Infrastructure flexibility |
| 8 | JSON Payloads | Universal, debuggable |
| 9 | Stateless Workers | Horizontal scaling |
| 10 | Dead Letter Queue | Handle permanent failures |
| 11 | CDC Support | High-throughput upgrade path (proposed) |
| 12 | Synchronous Orchestration | Simplicity for single-service sagas |
| 16 | Unified Storage Layer | DRY, full Redis support, data transfer |
| 23 | Pivot/Irreversible Steps | Handle irreversible operations (proposed) |
| 25 | Event-Driven Triggers | Auto-discovered, reactive sagas (proposed) |

