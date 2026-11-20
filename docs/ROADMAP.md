# Sagaz Roadmap

Where Sagaz is and where it goes next. The release ordering, entry conditions
and gates live in the [release plan](planning/release-plan.md); this page
summarizes it.

> **Latest release**: v2.2.0 (2026-11-20) | **Next**: v2.3.0, Maintenance, CDC & Ecosystem

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

Details for each release are in the [changelog](development/changelog.md).

## Next: v2.3.0, Maintenance, CDC & Ecosystem

One release instead of several patch and minor versions
([milestone](https://github.com/brunolnetto/sagaz/milestone/22)).

| Issue | Theme |
|-------|-------|
| [#498](https://github.com/brunolnetto/sagaz/issues/498) | Dependency updates, staying below Python 3.15 |
| [#499](https://github.com/brunolnetto/sagaz/issues/499) | Docs refresh: README, roadmap, ADR statuses, links |
| [#500](https://github.com/brunolnetto/sagaz/issues/500) | Test connection leak, SQLite write contention |
| [#495](https://github.com/brunolnetto/sagaz/issues/495) | CDC reader for the saga log export |
| [#501](https://github.com/brunolnetto/sagaz/issues/501) | Gradio saga asset monitor (ADR-039) |
| [#502](https://github.com/brunolnetto/sagaz/issues/502) | Schema registry for saga events (ADR-014) |
| [#190](https://github.com/brunolnetto/sagaz/issues/190) | StateChart phase 2: step charts and compensation re-entry (ADR-040) |
| [#517](https://github.com/brunolnetto/sagaz/issues/517) | Saga final state agrees with the result; PostgreSQL snapshots keep the configuration |

## Backlog

- **StateChart phase 3**: step charts for the declarative (decorator) engine, which has no
  state machine yet, and pivot/taint states in the chart (ADR-040).
- **Python 3.15**: not supported yet. Renovate stays on 3.14.

The planning history before v2.0 (sprint calendars, alternative schedules) is archived in
[ROADMAP_2026_PLANNING.md](archive/ROADMAP_2026_PLANNING.md).
