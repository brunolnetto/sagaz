# ADR-034: Multi-Region Saga Coordination

## Status

**Proposed** | Date: 2026-04-07 | Priority: Medium | Target: v2.4.0

**Implementation Status:**
- ⚪ Phase 1: Region Registry & Routing (Not Started)
- ⚪ Phase 2: Cross-Region Communication (Not Started)
- ⚪ Phase 3: Conflict Resolution & Consistency (Not Started)
- ⚪ Phase 4: Failover & Region Health (Not Started)
- ⚪ Phase 5: CLI & Observability (Not Started)

## Dependencies

**Prerequisites**:
- ADR-016: Unified Storage Layer (multi-region storage abstraction)
- ADR-020: Multi-Tenancy (tenant routing maps to regions)
- ADR-025: Event-Driven Triggers (cross-region events routed via broker)

**Synergies** (Optional):
- ADR-013: Fluss Analytics (aggregate cross-region events for global dashboards)
- ADR-033: Event Sourcing (cross-region events are globally ordered by region timestamp)
- ADR-029: Saga Choreography (choreography events can originate in any region)

**Roadmap**: **Phase 8 (v2.4.0)** — Global-scale deployments

## Context

Sagaz currently assumes a single-region deployment where all saga steps execute against a single storage backend and a single message broker. This creates latency and availability constraints for globally distributed applications.

### Single-Region Limitations

| Problem | Impact |
|---------|--------|
| All steps hit one DB region | 200–400 ms added latency for remote users |
| Single broker is SPOF | Region outage = full saga outage |
| Data residency laws ignored | GDPR, China MLPS, India DPDP: data must stay local |
| No active-active redundancy | DR failover requires manual intervention |
| Global workflows are awkward | Cross-continent saga requires VPN or API relay |

### Target Use Cases

| Scenario | Requirements |
|----------|-------------|
| Global e-commerce checkout | Payment in EU, inventory in US, shipping in APAC — each step runs in its local region |
| Financial cross-border settlement | Regulatory requirement: transaction records stay in country of origin |
| Multi-region active-active | If US-EAST goes down, US-WEST takes over seamlessly |
| Edge saga execution | IoT step executes on edge node, result propagated to central region |

---

## Decision

Implement **Multi-Region Saga Coordination** that allows individual saga steps to execute in designated regions, with a coordinator that handles routing, cross-region messaging, and conflict resolution.

### Design Principles

1. **Region affinity**: Each step can declare a `region` affinity; the executor routes it to the correct regional worker.
2. **Eventual consistency**: Cross-region state replication is asynchronous. Compensations must tolerate temporary inconsistency.
3. **Data residency enforcement**: Storage writes for a step happen only in the declared region.
4. **Active-active by default**: Any region can originate a saga; coordination happens transparently.
5. **Graceful degradation**: If the target region is unreachable, apply configurable fallback (wait, fail-fast, redirect to nearest healthy region).

---

## Proposed Architecture

### Region-Aware Step Definition

```python
class GlobalCheckoutSaga(Saga):
    async def build(self):
        await self.add_step(
            name="validate_payment",
            action=self._validate_payment,
            compensation=self._refund_payment,
            region="eu-west-1",           # EU data residency
        )
        await self.add_step(
            name="reserve_inventory",
            action=self._reserve_inventory,
            compensation=self._release_inventory,
            region="us-east-1",           # Inventory DB is in US
        )
        await self.add_step(
            name="schedule_shipping",
            action=self._schedule_shipping,
            region="ap-southeast-1",      # Shipping service in APAC
        )
```

### Region Registry

```python
# sagaz/core/regions.py
@dataclass
class Region:
    name: str                        # "eu-west-1"
    storage_url: str                 # Regional DB / Redis URL
    broker_url: str                  # Regional Kafka / RabbitMQ
    priority: int = 0                # 0 = primary; higher = fallback
    health_check_url: str = ""

class RegionRegistry:
    def register(self, region: Region) -> None: ...
    def get(self, name: str) -> Region: ...
    def healthy_regions(self) -> list[Region]: ...
    def nearest_to(self, origin: str) -> Region: ...
```

### Cross-Region Coordinator

```python
# sagaz/core/coordinator.py
class MultiRegionCoordinator:
    """Routes step execution to the appropriate regional worker."""

    async def execute_step(self, step: SagaStep, ctx: SagaContext) -> Any:
        region = self._registry.get(step.region or self._home_region)
        if not await region.is_healthy():
            region = self._registry.nearest_to(self._home_region)
        return await self._dispatch(step, ctx, region)

    async def _dispatch(self, step, ctx, region: Region) -> Any:
        # If local: call directly
        # If remote: publish to region's broker; await reply with correlation_id
        ...
```

### Conflict Resolution

Cross-region writes use **optimistic concurrency control** (OCC) with vector clocks:

```python
@dataclass
class RegionalVersion:
    region: str
    sequence: int

class ConflictResolver:
    policy: Literal["last_writer_wins", "first_writer_wins", "manual"]

    async def resolve(
        self,
        local: RegionalVersion,
        remote: RegionalVersion,
        event: SagaEvent,
    ) -> SagaEvent:
        match self.policy:
            case "last_writer_wins":
                return max(local, remote, key=lambda v: v.sequence)
            case "first_writer_wins":
                return min(local, remote, key=lambda v: v.sequence)
            case "manual":
                raise ConflictError(local, remote, event)
```

---

## Implementation Phases

### Phase 1: Region Registry & Routing (2 weeks)
- `Region` dataclass and `RegionRegistry` in `sagaz/core/regions.py`
- `SagaStep.region` field (optional)
- Multi-region section added to `sagaz.yaml` config schema
- Unit tests for registry lookup and fallback

### Phase 2: Cross-Region Communication (3 weeks)
- `MultiRegionCoordinator` dispatches steps to regional brokers
- Correlation-ID-based reply tracking for async cross-region calls
- Retry with regional failover on `asyncio.TimeoutError`
- Integration test with two in-process "regions" sharing a broker

### Phase 3: Conflict Resolution & Consistency (2 weeks)
- Vector clock implementation for `RegionalVersion`
- `ConflictResolver` with three policies
- OCC check on storage write; surface to caller on conflict
- Unit tests for all three resolution policies

### Phase 4: Failover & Region Health (1 week)
- Background health-check task per region (HTTP ping + storage latency probe)
- Automatic failover to next-priority region within 5 s of health-check failure
- `RegionHealthDegraded` Prometheus alert metric
- Integration test: kill one region mock, verify failover in < 5 s

### Phase 5: CLI & Observability (0.5 weeks)
- `sagaz region list` — show registry with health status
- `sagaz region failover --from <name> --to <name>` — manual failover
- Prometheus metrics: `sagaz_cross_region_latency_seconds`, `sagaz_region_failover_total`
- Grafana panel: per-region step execution count and latency

---

## Consequences

### Positive
- Steps execute close to their data sources → reduced latency
- Data residency laws respected per step
- Active-active redundancy enables fast, transparent DR
- Global sagas become first-class citizens

### Negative
- Cross-region network adds ~50–200 ms per remote step (unavoidable physics)
- Conflict resolution adds code complexity
- Debugging is harder across regions (mitigated by distributed tracing in ADR-013)
- Each region needs its own broker + storage deployment

### Mitigation
- `region=None` (default) uses home region → no overhead for single-region deployments
- Health checks are async and non-blocking
- Tracing integration correlates spans across regions (ADR-013 Fluss)

---

## Acceptance Criteria

- [ ] `Region` dataclass and `RegionRegistry` implemented
- [ ] `SagaStep.region` field accepted by `add_step()`
- [ ] `MultiRegionCoordinator` routes steps to regional workers
- [ ] Fallback to nearest healthy region on target region unavailability
- [ ] `ConflictResolver` with three policies; OCC enforced on storage writes
- [ ] `sagaz.yaml` config supports `regions:` block
- [ ] `sagaz region list` and `sagaz region failover` CLI commands
- [ ] Prometheus metrics for cross-region latency and failover count
- [ ] Integration test: two simulated regions, step executed in non-home region
- [ ] Integration test: region failover in < 5 s
- [ ] 90%+ coverage for new core code
- [ ] `docs/guides/multi-region.md` added

## Rejected Alternatives

### DNS-Based Routing Only
DNS TTLs are too coarse (60 s minimum) for sub-5 s failover needs.

### Single Global Broker
A single Kafka/RabbitMQ cluster spanning all regions would negate data residency benefits and becomes a bottleneck.

### Saga Duplication per Region
Running independent saga instances per region with reconciliation leads to split-brain. A single coordinator with regional workers is cleaner.
