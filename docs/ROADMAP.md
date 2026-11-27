# Sagaz Roadmap

Where Sagaz is and where it goes next. The release ordering, entry conditions
and gates live in the [release plan](planning/release-plan.md); this page
summarizes it.

> **Latest release**: v2.6.0 (2026-11-26) | **In development**: v2.6.1, Distributed Correctness & Reliability | **Next**: v2.7.0, Choreography Protocol

---

## Vision

**"The open-source distributed transaction platform that just works."**

Sagaz competes with AWS Step Functions, Temporal, and Azure Durable Functions by offering:
- ✅ **Exactly-once guarantees** (they don't have this)
- ✅ **Transactional outbox pattern** (they don't have this)
- ✅ **True code-first Python** (not JSON/YAML)
- ✅ **No vendor lock-in**
- ✅ **10x cost advantage**
- ✅ **Sub-10ms latency**

---

## Released

| Version | Wave | Theme | Highlights |
|---------|------|-------|------------|
| v1.5.0 | 0 | Governance & lightweight ops | Compliance (audit trails, retention, encryption), lifecycle hooks, GitFlow governance |
| v1.6.0 | 1 | Storage extensions | Dead letter queue (`sagaz dlq`), SQLite storage and outbox, cross-backend migration |
| v1.7.0 | 1b | StateChart migration, phase 1 | Saga and step lifecycles on `StateChart` (ADR-040), configuration in snapshots |
| v1.8.0 | 2 | Analytics & chaos | `ChaosMonkey`, embedded analytics pipeline (`sagaz[analytics]`), `sagaz monitor` dashboard |
| v1.9.0 | 3 | CLI v2, CDC, tenancy | Multi-tenancy, outbox CDC, cloud deployment CLI |
| v1.10.0 | 4 | Event-driven choreography | Choreographed sagas with delivery guarantees |
| v2.0.0 | 5 | Core extensions | Event sourcing, multi-region routing with data residency |
| v2.1.0 | 6 | Unified saga log | One OLTP model for orchestrated and choreographed sagas (ADR-041) |
| v2.2.0 | 7 | Streaming & historical analytics | Saga log exported to Fluss and tiered to Iceberg, Flink SQL, Prometheus (ADR-013) |
| v2.3.0 | 8 | Maintenance, CDC & ecosystem | Step charts with pivot/taint states, a CDC reader for the saga log export, a Gradio monitor, a schema registry for saga events |
| v2.4.0 | 9 | Developer experience | Retries, durability and run-once saga ids that hold, one failure contract (`SagaFailedError`), documentation that runs, the feature × mode matrix |
| v2.5.0 | 10 | Security & typing | Signed external context storage, dependencies without known advisories, CI gates on mypy, bandit, pip-audit and coverage |
| v2.6.0 | 11 | Mode parity | Orchestrated and choreographed sagas offer the same capabilities; `sagaz.Saga` replaces the classic engine; pivots and forward recovery; an event lineage |

Details for each release are in the [changelog](development/changelog.md).

## In development: v2.6.1, Distributed Correctness & Reliability

Corrections and small parity gaps found while delivering v2.6.0
([milestone](https://github.com/brunolnetto/sagaz/milestone/28)).

| Theme | Issues |
|-------|--------|
| What a saga accepts | A step method with a leading underscore ([#656](https://github.com/brunolnetto/sagaz/issues/656)); invalid definitions and settings become errors ([#660](https://github.com/brunolnetto/sagaz/issues/660)); `add_step(pivot=)` ([#678](https://github.com/brunolnetto/sagaz/issues/678)); a warning for pivots in parallel branches ([#679](https://github.com/brunolnetto/sagaz/issues/679)) |
| Sagas that stop after a pivot | Their two outcomes in the event stream, the unified log and the reports ([#673](https://github.com/brunolnetto/sagaz/issues/673)); listing them ([#674](https://github.com/brunolnetto/sagaz/issues/674)) |
| Choreography | Two time axes ([#628](https://github.com/brunolnetto/sagaz/issues/628)); a tracker that scales ([#632](https://github.com/brunolnetto/sagaz/issues/632)) |
| Operations | Signals for alerts that have no metric ([#637](https://github.com/brunolnetto/sagaz/issues/637)); read-side authentication for the visualization ([#643](https://github.com/brunolnetto/sagaz/issues/643)); the flaky lakehouse gate ([#614](https://github.com/brunolnetto/sagaz/issues/614)) |
| Documentation | An execution-guarantee matrix ([#641](https://github.com/brunolnetto/sagaz/issues/641)); release documents that stay current ([#642](https://github.com/brunolnetto/sagaz/issues/642)); a tour and examples on Read the Docs (#680, done) |

## Next: v2.7.0, Choreography Protocol

A choreography declared once and visible as a whole
([milestone](https://github.com/brunolnetto/sagaz/milestone/26)).

| Theme | Issues |
|-------|--------|
| The protocol and its map | Declared once and shared ([#626](https://github.com/brunolnetto/sagaz/issues/626)); the map across services, and acyclicity ([#627](https://github.com/brunolnetto/sagaz/issues/627)); a join ([#629](https://github.com/brunolnetto/sagaz/issues/629)); signed events ([#672](https://github.com/brunolnetto/sagaz/issues/672)) |
| After a point of no return | Forward recovery for a choreography ([#665](https://github.com/brunolnetto/sagaz/issues/665)); resuming a stopped saga ([#675](https://github.com/brunolnetto/sagaz/issues/675)) |
| Composition | A saga as a node of a choreography or of another saga ([#677](https://github.com/brunolnetto/sagaz/issues/677)); a handler still running when its transaction is compensated ([#676](https://github.com/brunolnetto/sagaz/issues/676)) |

## Later: v3.0.0, Removals

What 2.x deprecated goes away ([#630](https://github.com/brunolnetto/sagaz/issues/630)): the classic
`sagaz.core.saga.Saga`, the old metric names, the former keyword and option spellings.

## Backlog

- **Python 3.15**: not supported yet. Renovate stays on 3.14.
- **An API reference generated from docstrings** on the documentation site.

The planning history before v2.0 (sprint calendars, alternative schedules) is archived in
[ROADMAP_2026_PLANNING.md](archive/ROADMAP_2026_PLANNING.md).
