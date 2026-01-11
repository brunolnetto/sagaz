# Dataflow & Event Processing

This document describes how data flows through thesagaz system.

## Overview

```mermaid
sequenceDiagram
    participant App as Application
    participant Saga as Saga Engine
    participant DB as Database
    participant Worker as Outbox Worker
    
    App->>Saga: execute()
    Saga->>DB: BEGIN TX
    Saga->>DB: Step 1: action()<br/>INSERT outbox
    Saga->>DB: Step 2: action()<br/>INSERT outbox
    Saga->>DB: COMMIT TX
    Saga->>App: SagaResult
    
    Worker->>DB: poll pending
    Worker->>DB: claim + publish
```

---

## Use Case 1: Successful Saga Execution

```mermaid
sequenceDiagram
    participant App
    participant Saga
    participant Step
    participant DB
    participant Outbox
    participant Broker
    
    App->>Saga: execute()
    Saga->>Step: run step 1
    Step->>DB: action()
    Step->>Outbox: save_event()
    Step->>Saga: step 1 done
    Saga->>Step: run step 2
    Step->>DB: (repeat)
    Step->>Saga: all done
    Saga->>App: COMPLETED
    
    Outbox->>DB: poll pending
    Outbox->>DB: claim batch
    Outbox->>Broker: publish
    Outbox->>DB: mark sent
```

---

## Use Case 2: Saga Failure with Compensation

When Step 2 fails, compensations run in reverse order.

```mermaid
sequenceDiagram
    participant App
    participant Saga
    participant Step1 as Step 1
    participant Step2 as Step 2
    
    App->>Saga: execute()
    Saga->>Step1: run step 1
    Step1->>Saga: action() ✓
    Saga->>Step2: run step 2
    Step2-->>Saga: action() ✗ FAILS
    Note over Saga: COMPENSATING
    Saga->>Step1: compensate step 1
    Step1->>Saga: compensation()
    Saga->>App: COMPENSATED
```

---

## Use Case 3: Outbox Worker Processing

Multiple workers process events concurrently using `FOR UPDATE SKIP LOCKED`.

```mermaid
sequenceDiagram
    participant W1 as Worker 1
    participant W2 as Worker 2
    participant DB
    participant Broker
    
    W1->>DB: claim_batch()
    W2->>DB: claim_batch()
    DB->>W1: events [A, B]
    DB->>W2: events [C, D]<br/>(different via SKIP LOCKED)
    W1->>Broker: publish A
    W2->>Broker: publish C
    W1->>DB: mark A sent
    W1->>Broker: publish B
    W2->>DB: mark C sent
```

---

## Event State Machine

```mermaid
stateDiagram-v2
    [*] --> PENDING: Created by saga step
    
    PENDING --> CLAIMED: claim_batch()<br/>(FOR UPDATE SKIP LOCKED)
    
    CLAIMED --> SENT: publish_ok()
    CLAIMED --> FAILED: publish_fail()
    
    FAILED --> PENDING: retry_count < max<br/>(retry)
    FAILED --> DEAD_LETTER: retry_count >= max
    
    SENT --> [*]: done
    DEAD_LETTER --> [*]: manual review
```

---

## Message Flow to Broker

### RabbitMQ

```mermaid
graph LR
    Worker[Worker] -->|publish| Exchange["Exchange:<br/>saga-events (topic)"]
    Exchange -->|routing key = event_type| Q1["Queue:<br/>order.created"]
    Exchange --> Q2["Queue:<br/>payment.completed"]
```

### Kafka

```mermaid
graph TB
    Worker[Worker<br/>key = saga_id] -->|publish| Topic["Topic: saga-events"]
    Topic --> P0["Partition 0<br/>A, C"]
    Topic --> P1["Partition 1<br/>B, D"]
    Topic --> P2["Partition 2<br/>E, F"]
    
    Note[partitioned by saga_id for order]
```

---

## Consumer Inbox (Idempotency)

Prevents duplicate event processing on the consumer side.

```mermaid
sequenceDiagram
    participant C as Consumer Service
    participant I as Inbox Table
    participant B as Business Logic
    
    C->>I: receive event
    C->>I: check: exists?
    I->>C: NO (new event)
    C->>B: BEGIN TX
    C->>I: INSERT inbox
    C->>B: process event
    C->>B: COMMIT TX
    
    Note over C,I: Same event received again
    C->>I: receive SAME event
    C->>I: check: exists?
    I->>C: YES (duplicate)
    Note over C: SKIP processing
```

---

## Performance Characteristics

| Stage | Throughput | Latency | Bottleneck |
|-------|-----------|---------|------------|
| Event Insert (COPY) | 1,800/sec | <1ms | DB write speed |
| Event Claim | 1,500/sec | <5ms | Lock contention |
| Event Publish | 2,000/sec | <10ms | Broker ack |
| End-to-end | 1,200/sec | <50ms | Combined |

---

## Next Steps

- [Architecture Decisions](decisions.md) - Why we made these choices
- [Benchmarking Guide](../guides/benchmarking.md) - How to measure performance
