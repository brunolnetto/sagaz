# ADR-012: Synchronous Orchestration Model

## Status

**Accepted** - Implemented in v1.0

## Context

When implementing the saga pattern, there are two fundamental approaches:

1. **Synchronous Orchestration** - Steps execute as direct function calls within a single process
2. **Distributed/Async Orchestration** - Steps execute as separate services communicating via message broker

This ADR documents why Sagaz v1.0 implements synchronous orchestration and clarifies the role of `SagaListener`.

## The Two Models Compared

### Model A: Synchronous Orchestration (Sagaz v1.0)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SINGLE PROCESS                                │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    SAGA ORCHESTRATOR                          │  │
│  │                                                               │  │
│  │   saga.execute()                                              │  │
│  │        │                                                      │  │
│  │        ▼                                                      │  │
│  │   ┌─────────┐   ┌─────────┐   ┌─────────┐                    │  │
│  │   │ Step 1  │ → │ Step 2  │ → │ Step 3  │  (direct calls)    │  │
│  │   │  await  │   │  await  │   │  await  │                    │  │
│  │   └────┬────┘   └────┬────┘   └────┬────┘                    │  │
│  │        │             │             │                          │  │
│  │        ▼             ▼             ▼                          │  │
│  │   ┌─────────────────────────────────────────────────────┐    │  │
│  │   │  SagaListener.on_step_success() (observability)     │    │  │
│  │   └─────────────────────────────────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    OUTBOX TABLE                                │  │
│  │              (for downstream notifications)                    │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼ (OutboxWorker - separate process)
                          ┌──────────────┐
                          │   BROKER     │
                          └──────────────┘
                                 │
                                 ▼
                    ┌────────────────────┐
                    │  DOWNSTREAM SYSTEMS │
                    │  (Analytics, Audit) │
                    └────────────────────┘
```

**Characteristics:**
- Steps are `async def` functions called directly via `await`
- All steps run in the same Python process
- Saga state lives in memory during execution
- Outbox publishes events *after* saga completes/fails (for other systems to react)
- `SagaListener` provides lifecycle hooks for observability (logging, metrics, tracing)

### Model B: Distributed/Async Orchestration

```
┌──────────────────────┐                    ┌──────────────────────┐
│   ORCHESTRATOR       │                    │   PARTICIPANT        │
│   (Service A)        │                    │   (Service B)        │
│                      │                    │                      │
│  saga.start()        │                    │                      │
│      │               │                    │                      │
│      ▼               │                    │                      │
│  Outbox: Command ────┼────► Broker ──────►│ Consumer receives    │
│                      │      topic         │      │               │
│  Consumer waits...◄──┼────► Broker ◄──────┼── Outbox: Reply      │
│      │               │      topic         │                      │
│      ▼               │                    │                      │
│  Next step...        │                    │                      │
└──────────────────────┘                    └──────────────────────┘
```

**Characteristics:**
- Saga steps are separate microservices
- Communication happens via message broker (command/reply topics)
- Each service has message consumers ("listeners" in the broker sense)
- Saga state must be persisted (in DB) between steps
- Orchestrator waits for reply messages to proceed

---

## Decision

**Sagaz v1.0 implements Model A: Synchronous Orchestration**

### Rationale

#### 1. Target Use Case: Single-Service Sagas

Sagaz is designed for sagas that coordinate multiple operations **within a single service boundary**:

| Example | Steps |
|---------|-------|
| Order Processing | Validate → Reserve Inventory → Charge Payment → Create Order |
| Trade Execution | Validate Balance → Execute Trade → Update Position → Log Audit |
| User Onboarding | Create User → Initialize Settings → Send Welcome Email |

These sagas involve multiple database operations, external API calls, and business logic - all orchestrated within one service.

#### 2. Simplicity Over Complexity

| Aspect | Sync Orchestration | Distributed Orchestration |
|--------|-------------------|--------------------------|
| **Debugging** | ✅ Stack traces, local variables | ❌ Correlate across services |
| **Testing** | ✅ Simple unit tests, mocks | ❌ Integration tests required |
| **Transaction Boundaries** | ✅ Clear, controllable | ⚠️ Each service manages own |
| **Error Handling** | ✅ try/except, immediate | ❌ Timeout-based, async |
| **Deployment** | ✅ Single service | ❌ Multiple services + broker |
| **Latency** | ✅ Direct calls (~μs) | ❌ Message hops (~ms) |

#### 3. Outbox for the Right Purpose

The outbox pattern in Sagaz serves **downstream notification**, not **saga flow control**:

```python
class OrderSaga(Saga):
    listeners = [OutboxSagaListener(storage)]  # Publishes after saga completes
    
    @action("create_order")
    async def create_order(self, ctx):
        return await self.order_repo.create(ctx["order_data"])
```

**Flow:**
1. `create_order` executes (direct call)
2. `OutboxSagaListener.on_saga_complete()` writes event to outbox
3. OutboxWorker publishes to broker
4. **Other systems** (analytics, audit, inventory) consume the event

The saga itself doesn't wait for broker messages - it proceeds synchronously.

#### 4. SagaListener ≠ Message Consumer

This is a critical distinction:

| Sagaz `SagaListener` | Message Consumer (Broker Listener) |
|---------------------|-----------------------------------|
| **Purpose** | Observability hooks | Receive broker messages |
| **Invocation** | Called during `saga.execute()` | Called when message arrives |
| **Process** | Same as saga | Separate consumer process |
| **Examples** | `LoggingSagaListener`, `MetricsSagaListener` | Kafka Consumer, RabbitMQ Listener |
| **Pattern** | Observer Pattern | Pub/Sub Pattern |

```python
# Sagaz SagaListener - observability, NOT message consumption
class MetricsSagaListener(SagaListener):
    async def on_step_success(self, saga_name, step_name, ctx, result):
        STEP_COUNTER.labels(saga_name, step_name).inc()  # Record metric
        # NOT: receive a message from a broker
```

---

## Consequences

### Positive

1. **Lower Complexity** - No message serialization, broker configuration, or consumer management
2. **Faster Development** - Write sagas as simple async functions
3. **Better Debugging** - Full stack traces, breakpoints work
4. **Lower Latency** - No network hops between steps
5. **Easier Testing** - Mock functions, not message brokers

### Negative

1. **Single Process Boundary** - Steps must be callable from one Python process
2. **No Horizontal Scaling of Steps** - Can't scale individual steps independently  
3. **Process Restart = Saga Restart** - No built-in saga state persistence (yet)

### Neutral

1. **Outbox Still Needed** - For reliable downstream notifications
2. **Can Evolve to Distributed** - Architecture can migrate (see Design Doc: Distributed Saga Support)

---

## Alternatives Considered

### Alternative 1: Full Distributed Orchestration

**Rejected because:**
- Adds significant infrastructure complexity (broker, consumers, correlation IDs)
- Overkill for the primary use case (single-service saga coordination)
- Can be added in v2.0 if demand exists

### Alternative 2: Choreography-Based Sagas

```
Service A → Event "OrderCreated" → Broker
                                      ↓
                              Service B listens
                              Service B → Event "InventoryReserved" → Broker
                                                                        ↓
                                                                Service C listens
```

**Rejected because:**
- Harder to understand overall saga flow
- Difficult to handle compensation (who triggers what?)
- Debugging requires tracing across multiple services
- Sagaz's value proposition is **centralized orchestration**

### Alternative 3: Hybrid (Steps can be local or remote)

**Deferred to v2.0:**
- Would require step configuration: `@step("reserve", remote=True, topic="inventory.commands")`
- Adds complexity to step definition
- Can be added as opt-in feature later

---

## Documentation Impact

This ADR clarifies:

1. **README.md** - Should explain that Sagaz is for single-service sagas
2. **`SagaListener` docs** - Should clarify these are lifecycle observers, not message consumers
3. **Architecture Overview** - Already aligned with this decision

---

## Related Documents

- [Architecture Overview](../overview.md) - High-level system design
- [ADR-011: CDC Support](adr-011-cdc-support.md) - High-throughput outbox upgrade path
- [Design Doc: Distributed Saga Support](../design-distributed-saga-support.md) - Future v2.0 design (if implemented)

---

## References

- [Microservices Patterns: Saga](https://microservices.io/patterns/data/saga.html)
- [Orchestration vs Choreography](https://camunda.com/blog/2023/02/orchestration-vs-choreography/)
- [Microsoft: Saga distributed transactions pattern](https://learn.microsoft.com/en-us/azure/architecture/reference-architectures/saga/saga)
