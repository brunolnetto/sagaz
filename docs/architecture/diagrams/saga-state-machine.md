# Saga State Machine

Mermaid diagram showing saga execution states and transitions.

## Saga Execution Flow

```mermaid
stateDiagram-v2
    [*] --> PENDING: create()
    
    PENDING --> RUNNING: execute()
    
    RUNNING --> RUNNING: step_complete
    RUNNING --> COMPLETED: all_steps_done
    RUNNING --> COMPENSATING: step_failed
    
    COMPENSATING --> COMPENSATING: compensation_running
    COMPENSATING --> COMPENSATED: all_compensations_done
    COMPENSATING --> FAILED: compensation_failed
    
    COMPLETED --> [*]
    COMPENSATED --> [*]
    FAILED --> [*]
```

## Step Execution States

```mermaid
stateDiagram-v2
    [*] --> PENDING
    
    PENDING --> EXECUTING: start
    
    EXECUTING --> COMPLETED: success
    EXECUTING --> FAILED: error
    EXECUTING --> TIMEOUT: timeout
    
    FAILED --> EXECUTING: retry (if retries < max)
    TIMEOUT --> EXECUTING: retry (if retries < max)
    
    FAILED --> COMPENSATING: retries exhausted
    TIMEOUT --> COMPENSATING: retries exhausted
    
    COMPLETED --> [*]
    COMPENSATING --> [*]
```

## Compensation Flow

```mermaid
flowchart TD
    subgraph Saga["Saga: order-processing"]
        A[Step 1: Reserve Inventory] --> B[Step 2: Charge Payment]
        B --> C[Step 3: Ship Order]
    end
    
    C -->|FAILS| COMP[Start Compensation]
    
    subgraph Compensation["Compensation (Reverse Order)"]
        COMP --> C2[Comp 3: Cancel Shipment]
        C2 --> B2[Comp 2: Refund Payment]
        B2 --> A2[Comp 1: Release Inventory]
    end
    
    A2 --> DONE[COMPENSATED]
```

## Parallel Step Execution

```mermaid
flowchart LR
    START([Start]) --> P1[Step 1]
    START --> P2[Step 2]
    START --> P3[Step 3]
    
    P1 --> JOIN{All Complete?}
    P2 --> JOIN
    P3 --> JOIN
    
    JOIN -->|Yes| NEXT[Continue]
    JOIN -->|Any Failed| COMP[Compensate All]
```

## Status Enum Reference

| Status | Description |
|--------|-------------|
| `PENDING` | Saga created, not yet started |
| `RUNNING` | Steps are executing |
| `COMPLETED` | All steps succeeded |
| `COMPENSATING` | Failure detected, running compensations |
| `COMPENSATED` | All compensations completed |
| `FAILED` | Compensation also failed |
