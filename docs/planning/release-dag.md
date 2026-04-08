# Release DAG — Open PR Dependency Graph

> Auto-generated 2026-04-08. Covers 18 open PRs (features, placeholders, and Renovate dependency updates).

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
    PR69 -.->|"Requires ADR-016 ✅ + ADR-025 ✅"| PR69_note["Prerequisites met"]

    %% Style
    classDef implemented fill:#2d6a4f,stroke:#1b4332,color:#fff
    classDef placeholder fill:#6c757d,stroke:#495057,color:#fff
    classDef renovate fill:#0077b6,stroke:#023e8a,color:#fff

    class PR60,PR61,PR68,PR79,PR81 implemented
    class PR62,PR63,PR64,PR65,PR66,PR67,PR69,PR70,PR71,PR72,PR74 placeholder
    class PR75,PR76 renovate
```

## Merge Order

### Wave 1 — Independent (no blockers, implemented) → v1.2.0

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

### Wave 2 — DLQ + AlertManager → v1.3.0

| PR | Feature | Depends On | Files |
|----|---------|------------|-------|
| **#60** | Dead Letter Queue | main | 8 |
| **#61** | AlertManager Rules | #60 | 3 |

### Wave 3 — Storage + Analytics → v1.4.0

| PR | Feature | Depends On | Files |
|----|---------|------------|-------|
| **#62** | SQLite Backend | #60 | placeholder |
| **#63** | Storage Migration | #62 | placeholder |
| **#74** | sqldim Analytics | #62 | placeholder |

### Wave 4 — CLI + Visualization → v1.5.0

| PR | Feature | Depends On | Files |
|----|---------|------------|-------|
| **#64** | CLI v1.0 | #63 | placeholder |
| **#71** | Visualization UI | #74 | placeholder |

### Wave 5 — Q3/Q4 Deferred → v2.0.0+

| PR | Feature | ADR | Target |
|----|---------|-----|--------|
| **#65** | CLI v2.0 | — | v2.0.0 |
| **#66** | CDC / Debezium | ADR-011 | v2.0.0 |
| **#67** | Fluss + Iceberg | ADR-013 | v2.1.0 |
| **#69** | Choreography | ADR-029 | v2.2.0 |
| **#70** | Event Sourcing | ADR-033 | v2.3.0 |
| **#72** | Multi-Region | ADR-034 | v2.4.0 |

## Release Roadmap

> Current release: **v1.1.2**

All Wave 1 PRs add new modules without modifying existing APIs.
Wave 5 targets the v2.x line because choreography and event sourcing
will require core `Saga` interface changes (breaking).

| Release | Type | PRs | Rationale |
|---------|------|-----|-----------|
| **v1.2.0** | MINOR | #68, #79, #81, #75, #76 | 3 new feature modules (additive), 2 dep bumps |
| **v1.3.0** | MINOR | #60, #61 | DLQ + AlertManager (new outbox/monitoring APIs) |
| **v1.4.0** | MINOR | #62, #63, #74 | SQLite backend, migration layer, analytics |
| **v1.5.0** | MINOR | #64, #71 | CLI v1 + visualization dashboard |
| **v2.0.0** | MAJOR | #65, #66, #67, #69, #70, #72 | Choreography + event sourcing change core APIs |

### Why v1.2.0 instead of v2.0.0 for saga versioning?

ADR-018 originally targeted v2.0.0, but the implementation (#81) is
purely additive: it introduces `sagaz.versioning` without modifying any
existing public API. Per semver, a MINOR bump is correct. The v2.0.0
milestone is reserved for Wave 5 features that *do* alter the core
`Saga` interface (choreography mode, event sourcing strategy).

## Legend

- **implemented** (green): PR has real code changes, tests, and is review-ready
- **placeholder** (grey): PR exists with skeleton commit only — implementation pending
- **renovate** (blue): Automated dependency updates
