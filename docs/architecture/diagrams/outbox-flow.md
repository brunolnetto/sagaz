# Outbox Flow

Mermaid diagrams showing transactional outbox event flow.

## End-to-End Flow

```mermaid
sequenceDiagram
    participant App as Application
    participant Saga as Saga Engine
    participant DB as PostgreSQL
    participant Worker as Outbox Worker
    participant Broker as RabbitMQ/Kafka
    participant Consumer as Consumer Service

    App->>Saga: execute(context)
    
    activate Saga
    Saga->>DB: BEGIN TRANSACTION
    
    loop For each step
        Saga->>Saga: step.action()
        Saga->>DB: INSERT INTO saga_outbox
    end
    
    Saga->>DB: COMMIT
    deactivate Saga
    
    Saga-->>App: SagaResult
    
    Note over Worker: Async processing
    
    loop Poll interval
        Worker->>DB: SELECT ... FOR UPDATE SKIP LOCKED
        DB-->>Worker: Pending events
        
        Worker->>DB: UPDATE status = 'claimed'
        
        Worker->>Broker: publish(event)
        Broker-->>Worker: ack
        
        Worker->>DB: UPDATE status = 'sent'
    end
    
    Broker->>Consumer: deliver(event)
    Consumer->>Consumer: process()
```

## Event State Machine

```mermaid
stateDiagram-v2
    [*] --> PENDING: INSERT event
    
    PENDING --> CLAIMED: worker claims batch
    
    CLAIMED --> SENT: publish success
    CLAIMED --> FAILED: publish error
    
    FAILED --> PENDING: retry (if count < max)
    FAILED --> DEAD_LETTER: retry exhausted
    
    SENT --> [*]: archived
    DEAD_LETTER --> [*]: manual review
```

## Worker Claim Process

```mermaid
flowchart TD
    subgraph Worker1["Worker 1"]
        W1_POLL[Poll pending events]
        W1_CLAIM[Claim with SKIP LOCKED]
        W1_PUB[Publish to broker]
        W1_MARK[Mark as SENT]
    end
    
    subgraph Worker2["Worker 2"]
        W2_POLL[Poll pending events]
        W2_CLAIM[Claim with SKIP LOCKED]
        W2_PUB[Publish to broker]
        W2_MARK[Mark as SENT]
    end
    
    subgraph Database["PostgreSQL"]
        OUTBOX[(saga_outbox)]
    end
    
    subgraph Broker["Message Broker"]
        QUEUE[/Event Queue/]
    end
    
    W1_POLL --> W1_CLAIM
    W2_POLL --> W2_CLAIM
    
    W1_CLAIM <--> OUTBOX
    W2_CLAIM <--> OUTBOX
    
    W1_CLAIM --> W1_PUB
    W2_CLAIM --> W2_PUB
    
    W1_PUB --> QUEUE
    W2_PUB --> QUEUE
    
    W1_PUB --> W1_MARK
    W2_PUB --> W2_MARK
    
    W1_MARK --> OUTBOX
    W2_MARK --> OUTBOX
```

## Database Transaction Boundary

```mermaid
flowchart LR
    subgraph TX["Single Transaction"]
        A[Business Logic] --> B[Update Domain]
        B --> C[Insert Outbox Event]
    end
    
    TX -->|COMMIT| DB[(PostgreSQL)]
    
    DB -->|Async| WORKER[Outbox Worker]
    WORKER --> BROKER[Message Broker]
```

## Failure & Retry Flow

```mermaid
flowchart TD
    CLAIM[Claim Event] --> PUB{Publish}
    
    PUB -->|Success| SENT[Mark SENT]
    PUB -->|Failure| FAILED[Mark FAILED]
    
    FAILED --> CHECK{retry_count < max?}
    
    CHECK -->|Yes| PENDING[Reset to PENDING]
    PENDING --> |Next poll| CLAIM
    
    CHECK -->|No| DLQ[Move to DEAD_LETTER]
    
    DLQ --> ALERT[Alert + Manual Review]
```

## Consumer Inbox (Idempotency)

```mermaid
sequenceDiagram
    participant Broker as Message Broker
    participant Consumer as Consumer Service
    participant Inbox as consumer_inbox
    participant Logic as Business Logic

    Broker->>Consumer: deliver(event_id: ABC)
    
    Consumer->>Inbox: SELECT WHERE event_id = ABC
    
    alt Event not in inbox
        Inbox-->>Consumer: NOT FOUND
        
        Consumer->>Inbox: BEGIN TX
        Consumer->>Inbox: INSERT event_id = ABC
        Consumer->>Logic: process(event)
        Consumer->>Inbox: COMMIT
        
    else Event already processed
        Inbox-->>Consumer: FOUND
        Consumer->>Consumer: SKIP (duplicate)
    end
```
