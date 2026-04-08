# Release DAG — Open PR Dependency Graph

> Auto-generated 2026-04-08. Represents the merge ordering for all open PRs.

## Mermaid Diagram

```mermaid
graph TD
    subgraph "Q2 2026 — v1.x Pipeline"
        PR60["#60 DLQ<br/><i>feat(outbox)</i><br/>8 files"]
        PR61["#61 AlertManager Rules<br/><i>feat(monitoring)</i><br/>3 files"]
        PR62["#62 SQLite Backend<br/><i>feat(storage)</i><br/>placeholder"]
        PR63["#63 Storage Migration<br/><i>feat(storage)</i><br/>placeholder"]
        PR64["#64 CLI v1.0<br/><i>feat(cli)</i><br/>placeholder"]
    end

    subgraph "Q2 2026 — v2.x Pipeline"
        PR74["#74 sqldim Analytics<br/><i>feat(monitoring)</i><br/>placeholder"]
        PR71["#71 Visualization UI<br/><i>feat(visualization)</i><br/>placeholder"]
    end

    subgraph "Independent — Ready to Merge"
        PR68["#68 Multi-Tenancy<br/><i>feat(sagaz)</i><br/>5 files"]
        PR79["#79 Chaos Engineering<br/><i>feat(testing)</i><br/>5 files"]
        PR81["#81 Saga Versioning<br/><i>feat(saga)</i><br/>10 files"]
    end

    subgraph "Q3–Q4 2026 — Deferred"
        PR65["#65 CLI v2.0<br/><i>feat(cli)</i><br/>placeholder"]
        PR66["#66 CDC / Debezium<br/><i>feat(integrations)</i><br/>placeholder"]
        PR67["#67 Fluss + Iceberg<br/><i>feat(monitoring)</i><br/>placeholder"]
        PR69["#69 Choreography<br/><i>feat(saga)</i><br/>placeholder"]
        PR70["#70 Event Sourcing<br/><i>feat(storage)</i><br/>placeholder"]
        PR72["#72 Multi-Region<br/><i>feat(sagaz)</i><br/>placeholder"]
    end

    subgraph "Renovate"
        PR75["#75 pytest 9.x"]
        PR76["#76 cp-kafka 7.x"]
    end

    %% Q2 v1 chain
    PR60 --> PR61
    PR60 --> PR62
    PR62 --> PR63
    PR62 --> PR74
    PR63 --> PR64
    PR74 --> PR71

    %% Q3+ deferred dependencies
    PR64 --> PR65
    PR66 --> PR67
    PR68 --> PR72
    PR69 -.->|"ADR-016 ✅ + ADR-025 ✅"| PR69

    %% Style
    classDef implemented fill:#2d6a4f,stroke:#1b4332,color:#fff
    classDef placeholder fill:#6c757d,stroke:#495057,color:#fff
    classDef renovate fill:#0077b6,stroke:#023e8a,color:#fff

    class PR60,PR61,PR68,PR79,PR81 implemented
    class PR62,PR63,PR64,PR65,PR66,PR67,PR69,PR70,PR71,PR72,PR74 placeholder
    class PR75,PR76 renovate
```

## Merge Order

### Wave 1 — Independent (no blockers, implemented)

| PR | Feature | ADR | Files | Copilot Reviews |
|----|---------|-----|-------|-----------------|
| **#79** | Chaos Engineering | ADR-017 | 5 | 3 actionable |
| **#81** | Saga Versioning | ADR-018 | 10 | 5 actionable |
| **#68** | Multi-Tenancy | ADR-020 | 5 | 7 actionable |

### Wave 1a — Renovate dependency updates

| PR | Feature | ADR | Files | Copilot Reviews |
|----|---------|-----|-------|-----------------|
| **#75** | pytest 9.x (renovate) | — | 1 | — |
| **#76** | cp-kafka 7.x (renovate) | — | 1 | — |

### Wave 2 — DLQ + AlertManager (v1.1.0)

| PR | Feature | Depends On | Files |
|----|---------|------------|-------|
| **#60** | Dead Letter Queue | main | 8 |
| **#61** | AlertManager Rules | #60 | 3 |

### Wave 3 — Storage + Analytics (v1.3.1 / v2.2.0-beta)

| PR | Feature | Depends On | Files |
|----|---------|------------|-------|
| **#62** | SQLite Backend | #60 | placeholder |
| **#63** | Storage Migration | #62 | placeholder |
| **#74** | sqldim Analytics | #62 | placeholder |

### Wave 4 — CLI + Visualization (v1.5.0 / v2.2.0-beta)

| PR | Feature | Depends On | Files |
|----|---------|------------|-------|
| **#64** | CLI v1.0 | #63 | placeholder |
| **#71** | Visualization UI | #74 | placeholder |

### Wave 5 — Q3/Q4 Deferred

| PR | Feature | ADR | Target |
|----|---------|-----|--------|
| **#65** | CLI v2.0 | — | v2.0.0 (Q3) |
| **#66** | CDC / Debezium | ADR-011 | v2.0.0 (Q3) |
| **#67** | Fluss + Iceberg | ADR-013 | v2.1.0 (Q3) |
| **#69** | Choreography | ADR-029 | v2.2.0 (Q3) |
| **#70** | Event Sourcing | ADR-033 | v2.3.0 (Q4) |
| **#72** | Multi-Region | ADR-034 | v2.4.0 (Q4) |

## Legend

- **implemented** (green): PR has real code changes, tests, and is review-ready
- **placeholder** (grey): PR exists with skeleton commit only — implementation pending
- **renovate** (blue): Automated dependency updates
