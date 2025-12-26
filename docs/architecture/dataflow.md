# Dataflow & Event Processing

This document describes how data flows through thesagaz system.

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SAGA EXECUTION                                 │
│                                                                             │
│   Application         Saga Engine          Database           Outbox Worker │
│       │                   │                   │                     │       │
│       │  execute()        │                   │                     │       │
│       ├──────────────────►│                   │                     │       │
│       │                   │                   │                     │       │
│       │                   │ BEGIN TX          │                     │       │
│       │                   ├──────────────────►│                     │       │
│       │                   │                   │                     │       │
│       │                   │ Step 1: action()  │                     │       │
│       │                   │ INSERT outbox     │                     │       │
│       │                   ├──────────────────►│                     │       │
│       │                   │                   │                     │       │
│       │                   │ Step 2: action()  │                     │       │
│       │                   │ INSERT outbox     │                     │       │
│       │                   ├──────────────────►│                     │       │
│       │                   │                   │                     │       │
│       │                   │ COMMIT TX         │                     │       │
│       │                   ├──────────────────►│                     │       │
│       │                   │                   │                     │       │
│       │  SagaResult       │                   │                     │       │
│       │◄──────────────────┤                   │                     │       │
│       │                   │                   │                     │       │
│       │                   │                   │  poll pending       │       │
│       │                   │                   │◄────────────────────┤       │
│       │                   │                   │                     │       │
│       │                   │                   │  claim + publish    │       │
│       │                   │                   │◄────────────────────┤       │
│       │                   │                   │                     │       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Use Case 1: Successful Saga Execution

```
┌────────┐     ┌────────┐     ┌────────┐     ┌────────┐     ┌────────┐
│  App   │     │  Saga  │     │  Step  │     │   DB   │     │ Outbox │
└───┬────┘     └───┬────┘     └───┬────┘     └───┬────┘     └───┬────┘
    │              │              │              │              │
    │ execute()    │              │              │              │
    ├─────────────►│              │              │              │
    │              │              │              │              │
    │              │ run step 1   │              │              │
    │              ├─────────────►│              │              │
    │              │              │              │              │
    │              │              │ action()     │              │
    │              │              ├─────────────►│              │
    │              │              │              │              │
    │              │              │ save_event() │              │
    │              │              ├─────────────►│              │
    │              │              │              │              │
    │              │ step 1 done  │              │              │
    │              │◄─────────────┤              │              │
    │              │              │              │              │
    │              │ run step 2   │              │              │
    │              ├─────────────►│              │              │
    │              │              │ (repeat)     │              │
    │              │              ├─────────────►│              │
    │              │              │              │              │
    │              │ all done     │              │              │
    │              │◄─────────────┤              │              │
    │              │              │              │              │
    │ COMPLETED    │              │              │              │
    │◄─────────────┤              │              │              │
    │              │              │              │              │
    │              │              │              │ poll pending │
    │              │              │              │◄─────────────┤
    │              │              │              │              │
    │              │              │              │ claim batch  │
    │              │              │              │◄─────────────┤
    │              │              │              │              │
    │              │              │              │ publish      │
    │              │              │              │─────────────►│ Broker
    │              │              │              │              │
    │              │              │              │ mark sent    │
    │              │              │              │◄─────────────┤
    │              │              │              │              │
```

---

## Use Case 2: Saga Failure with Compensation

When Step 2 fails, compensations run in reverse order.

```
┌────────┐     ┌────────┐     ┌────────┐     ┌────────┐
│  App   │     │  Saga  │     │ Step 1 │     │ Step 2 │
└───┬────┘     └───┬────┘     └───┬────┘     └───┬────┘
    │              │              │              │
    │ execute()    │              │              │
    ├─────────────►│              │              │
    │              │              │              │
    │              │ run step 1   │              │
    │              ├─────────────►│              │
    │              │              │              │
    │              │ action() ✓   │              │
    │              │◄─────────────┤              │
    │              │              │              │
    │              │ run step 2   │              │
    │              ├─────────────────────────────►
    │              │              │              │
    │              │              │   action() ✗ │
    │              │◄─────────────────────────────  FAILS
    │              │              │              │
    │              │ COMPENSATING │              │
    │              │              │              │
    │              │ compensate step 1           │
    │              ├─────────────►│              │
    │              │              │              │
    │              │ compensation()│             │
    │              │◄─────────────┤              │
    │              │              │              │
    │ COMPENSATED  │              │              │
    │◄─────────────┤              │              │
    │              │              │              │
```

---

## Use Case 3: Outbox Worker Processing

Multiple workers process events concurrently using `FOR UPDATE SKIP LOCKED`.

```
┌──────────┐     ┌──────────┐     ┌────────┐     ┌────────┐
│ Worker 1 │     │ Worker 2 │     │   DB   │     │ Broker │
└────┬─────┘     └────┬─────┘     └───┬────┘     └───┬────┘
     │                │               │               │
     │ claim_batch()  │               │               │
     ├───────────────────────────────►│               │
     │                │               │               │
     │                │ claim_batch() │               │
     │                ├──────────────►│               │
     │                │               │               │
     │ events [A, B]  │               │               │
     │◄───────────────────────────────┤               │
     │                │               │               │
     │                │ events [C, D] │  (different   │
     │                │◄──────────────┤   events due  │
     │                │               │   to SKIP     │
     │                │               │   LOCKED)     │
     │                │               │               │
     │ publish A      │               │               │
     ├───────────────────────────────────────────────►│
     │                │               │               │
     │                │ publish C     │               │
     │                ├──────────────────────────────►│
     │                │               │               │
     │ mark A sent    │               │               │
     ├───────────────────────────────►│               │
     │                │               │               │
     │ publish B      │               │               │
     ├───────────────────────────────────────────────►│
     │                │               │               │
     │                │ mark C sent   │               │
     │                ├──────────────►│               │
     │                │               │               │
```

---

## Event State Machine

```
                         ┌─────────────────────────────────────┐
                         │                                     │
                         │    ┌───────────┐                    │
                         │    │  PENDING  │◄───── Created by   │
                         │    └─────┬─────┘       saga step    │
                         │          │                          │
                         │    claim_batch()                    │
                         │    (FOR UPDATE SKIP LOCKED)         │
                         │          │                          │
                         │    ┌─────▼─────┐                    │
                  ┌──────┴────│  CLAIMED  │────────┐           │
                  │           └───────────┘        │           │
                  │                                │           │
            publish_ok()                    publish_fail()     │
                  │                                │           │
            ┌─────▼─────┐                  ┌──────▼──────┐     │
            │   SENT    │                  │   FAILED    │     │
            │           │                  │             │     │
            │  (done)   │                  │ retry_count │     │
            └───────────┘                  │    += 1     │     │
                                           └──────┬──────┘     │
                                                  │            │
                                    ┌─────────────┴────────────┤
                                    │                          │
                              retry_count < max?         retry_count >= max?
                                    │                          │
                              ┌─────▼─────┐             ┌──────▼──────┐
                              │  PENDING  │             │ DEAD_LETTER │
                              │  (retry)  │             │             │
                              └───────────┘             │  (manual    │
                                                        │   review)   │
                                                        └─────────────┘
```

---

## Message Flow to Broker

### RabbitMQ

```
┌─────────────┐    ┌─────────────────────────────────────────┐
│   Worker    │    │              RabbitMQ                    │
│             │    │                                          │
│             │    │  ┌───────────────────────┐              │
│  publish()  │───►│  │   saga-events         │  Exchange    │
│             │    │  │   (topic)             │              │
│             │    │  └───────────┬───────────┘              │
│             │    │              │                          │
│             │    │    routing key = event_type             │
│             │    │              │                          │
│             │    │  ┌───────────▼───────────┐              │
│             │    │  │  order.created        │  Queue       │
│             │    │  └───────────────────────┘              │
│             │    │  ┌───────────────────────┐              │
│             │    │  │  payment.completed    │  Queue       │
│             │    │  └───────────────────────┘              │
│             │    │                                          │
└─────────────┘    └─────────────────────────────────────────┘
```

### Kafka

```
┌─────────────┐    ┌─────────────────────────────────────────┐
│   Worker    │    │              Kafka                       │
│             │    │                                          │
│             │    │  ┌─────────────────────────────────────┐│
│  publish()  │───►│  │  Topic: saga-events                 ││
│             │    │  │                                     ││
│   key =     │    │  │  ┌────────┐ ┌────────┐ ┌────────┐  ││
│   saga_id   │    │  │  │ Part 0 │ │ Part 1 │ │ Part 2 │  ││
│             │    │  │  │        │ │        │ │        │  ││
│             │    │  │  │  A, C  │ │  B, D  │ │  E, F  │  ││
│             │    │  │  └────────┘ └────────┘ └────────┘  ││
│             │    │  │                                     ││
│             │    │  │  (partitioned by saga_id for order) ││
│             │    │  └─────────────────────────────────────┘│
│             │    │                                          │
└─────────────┘    └─────────────────────────────────────────┘
```

---

## Consumer Inbox (Idempotency)

Prevents duplicate event processing on the consumer side.

```
┌──────────────┐     ┌──────────────┐     ┌────────────────┐
│   Consumer   │     │    Inbox     │     │   Business     │
│   Service    │     │    Table     │     │   Logic        │
└──────┬───────┘     └──────┬───────┘     └───────┬────────┘
       │                    │                     │
       │ receive event      │                     │
       ├───────────────────►│                     │
       │                    │                     │
       │ check: exists?     │                     │
       ├───────────────────►│                     │
       │                    │                     │
       │ NO (new event)     │                     │
       │◄───────────────────┤                     │
       │                    │                     │
       │ BEGIN TX           │                     │
       ├─────────────────────────────────────────►│
       │                    │                     │
       │ INSERT inbox       │                     │
       ├───────────────────►│                     │
       │                    │                     │
       │ process event      │                     │
       ├─────────────────────────────────────────►│
       │                    │                     │
       │ COMMIT TX          │                     │
       ├─────────────────────────────────────────►│
       │                    │                     │
       │                    │                     │
       │ receive SAME event │                     │
       ├───────────────────►│                     │
       │                    │                     │
       │ check: exists?     │                     │
       ├───────────────────►│                     │
       │                    │                     │
       │ YES (duplicate)    │                     │
       │◄───────────────────┤                     │
       │                    │                     │
       │ SKIP processing    │                     │
       │                    │                     │
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
