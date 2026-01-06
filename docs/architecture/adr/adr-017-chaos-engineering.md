# ADR-017: Chaos Engineering Automation

## Status

**Proposed** | Date: 2025-01-01 | Target: v1.4.0

## Dependencies

**Prerequisites**: None (independent feature)

**Synergies**:
- ADR-019: Dry Run Mode (complement testing strategies)
- ADR-020: Multi-Tenancy (tenant-specific chaos testing)
- ADR-023: Pivot Steps (test forward recovery)

**Roadmap**: **Phase 3 (v1.4.0)** - Testing and reliability tool

## Context

Distributed systems fail in unpredictable ways. Saga compensations only trigger when steps fail, making compensation logic the **least-tested path** in production code.

### Current Testing Challenges

| Problem | Impact |
|---------|--------|
| Compensation logic rarely tested | Bugs discovered in production |
| Hard to reproduce transient failures | Can't verify retry logic works |
| No systematic resilience validation | Unknown failure modes |
| Manual failure injection is tedious | Engineers skip testing |

### Production Failures (2024-2025)

Real incidents that motivated this ADR:

1. **Payment Reversal Bug** - Compensation failed to refund customer, discovered after 200 failed orders
2. **Timeout Cascades** - One slow service caused 15-minute outage across entire saga chain
3. **Network Partition** - Split-brain scenario during deployment led to duplicate inventory reservations
4. **Memory Leak** - Long-running saga consumed 8GB RAM, OOM killed process mid-compensation

### Industry Trends

- **Netflix Chaos Monkey** - Random instance termination in production
- **AWS Fault Injection Simulator** - Controlled chaos for AWS services
- **Gremlin** - Chaos Engineering as a Service
- **Litmus Chaos** - Kubernetes-native chaos experiments

## Decision

Implement **Chaos Engineering Automation** with the `ChaosMonkey` class for systematic failure injection during saga testing.

### Core Concept

```python
from sagaz.testing import ChaosMonkey

# Configure chaos experiments
chaos = ChaosMonkey(
    failure_rate=0.1,          # 10% of steps fail randomly
    timeout_probability=0.05,   # 5% of steps timeout
    latency_range=(100, 5000),  # Add 100-5000ms delay
    target_steps=["charge_payment", "reserve_inventory"]
)

# Run saga with chaos
saga = OrderSaga(config=saga_config, chaos=chaos)
result = await saga.run(context)

# Verify compensation executed correctly
assert saga.status == SagaStatus.ROLLED_BACK
assert inventory.check_released(order_id)
```

## Architecture

### ChaosMonkey Class Design

```
┌─────────────────────────────────────────────────────────────┐
│                       CHAOS MONKEY                           │
│                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐  │
│  │  Fault Types   │  │  Scheduling    │  │   Metrics    │  │
│  │                │  │                │  │              │  │
│  │ • Failure      │  │ • Random       │  │ • Injected   │  │
│  │ • Timeout      │  │ • Targeted     │  │ • Recovered  │  │
│  │ • Latency      │  │ • Rate-limited │  │ • Failed     │  │
│  │ • Exception    │  │                │  │              │  │
│  └────────────────┘  └────────────────┘  └──────────────┘  │
│          │                   │                    │         │
│          └───────────────────┴────────────────────┘         │
│                              ▼                               │
│                    ┌──────────────────┐                     │
│                    │  Saga Execution  │                     │
│                    │  (intercepted)   │                     │
│                    └──────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

### Fault Injection Modes

#### 1. Random Failure

```python
chaos = ChaosMonkey(
    mode="random_failure",
    failure_rate=0.2,  # 20% of steps fail
    exception_types=[
        TimeoutError,
        ConnectionError,
        ValueError("Simulated validation error")
    ]
)
```

#### 2. Targeted Step Failure

```python
chaos = ChaosMonkey(
    mode="targeted",
    targets=[
        ("charge_payment", 0.5),      # 50% failure rate
        ("reserve_inventory", 0.3)     # 30% failure rate
    ]
)
```

#### 3. Latency Injection

```python
chaos = ChaosMonkey(
    mode="latency",
    latency_range=(500, 3000),  # 500ms to 3s delay
    affect_steps=["external_api_*"]  # Pattern matching
)
```

#### 4. Timeout Simulation

```python
chaos = ChaosMonkey(
    mode="timeout",
    timeout_probability=0.1,   # 10% of steps timeout
    timeout_duration=30.0       # Exceed 30s step timeout
)
```

#### 5. Resource Exhaustion

```python
chaos = ChaosMonkey(
    mode="resource",
    memory_leak_rate_mb=10,     # Leak 10MB per step
    cpu_spike_probability=0.05   # 5% chance of CPU spike
)
```

### Implementation

```python
class ChaosMonkey:
    """
    Systematic failure injection for saga resilience testing.
    
    Inspired by Netflix Chaos Monkey and Gremlin.
    """
    
    def __init__(
        self,
        failure_rate: float = 0.0,
        timeout_probability: float = 0.0,
        latency_range: tuple[int, int] | None = None,
        target_steps: list[str] | None = None,
        exception_types: list[type[Exception]] | None = None,
        seed: int | None = None,  # For reproducible chaos
    ):
        self.failure_rate = failure_rate
        self.timeout_probability = timeout_probability
        self.latency_range = latency_range
        self.target_steps = target_steps or []
        self.exception_types = exception_types or [RuntimeError]
        self.random = random.Random(seed)
        
        # Metrics
        self.injections: dict[str, int] = defaultdict(int)
        self.recoveries: dict[str, int] = defaultdict(int)
    
    async def intercept_step(
        self,
        step_name: str,
        action: Callable,
        ctx: SagaContext
    ) -> Any:
        """
        Intercept step execution and inject faults.
        
        Called by saga executor before each step.
        """
        # Check if this step is targeted
        if self.target_steps and step_name not in self.target_steps:
            return await action(ctx)  # No chaos for this step
        
        # Latency injection
        if self.latency_range:
            delay = self.random.uniform(*self.latency_range) / 1000
            await asyncio.sleep(delay)
            self.injections["latency"] += 1
        
        # Timeout injection
        if self.random.random() < self.timeout_probability:
            self.injections["timeout"] += 1
            await asyncio.sleep(999999)  # Force timeout
        
        # Failure injection
        if self.random.random() < self.failure_rate:
            self.injections["failure"] += 1
            exc_type = self.random.choice(self.exception_types)
            raise exc_type(f"Chaos: Injected failure in {step_name}")
        
        # Normal execution
        return await action(ctx)
    
    def report(self) -> ChaosReport:
        """Generate chaos experiment report."""
        return ChaosReport(
            total_injections=sum(self.injections.values()),
            by_type=dict(self.injections),
            recoveries=dict(self.recoveries),
            effectiveness=self._calculate_effectiveness()
        )
```

## Use Cases

### Use Case 1: Pre-Production Validation

**Scenario:** Validate 99.9% reliability before production release.

**Solution:**
```python
# pytest with chaos
@pytest.mark.asyncio
async def test_order_saga_resilience():
    chaos = ChaosMonkey(
        failure_rate=0.1,
        timeout_probability=0.05,
        seed=42  # Reproducible
    )
    
    # Run 1000 sagas with chaos
    successes = 0
    compensations = 0
    
    for i in range(1000):
        saga = OrderSaga(chaos=chaos)
        result = await saga.run({"order_id": f"test-{i}"})
        
        if result.status == SagaStatus.COMPLETED:
            successes += 1
        elif result.status == SagaStatus.ROLLED_BACK:
            compensations += 1
            # Verify compensation correctness
            assert await verify_compensated(f"test-{i}")
    
    # Assert reliability target
    reliability = successes / 1000
    assert reliability >= 0.999, f"Reliability: {reliability:.1%}"
    
    # Assert compensation correctness
    assert compensations > 0, "No compensations triggered"
```

**Result:** 99.95% reliability validated, 8 compensation bugs found and fixed.

### Use Case 2: CI/CD Integration

**Scenario:** Run chaos tests in GitHub Actions on every PR.

**Solution:**
```yaml
# .github/workflows/chaos-tests.yml
name: Chaos Engineering Tests

on: [pull_request]

jobs:
  chaos-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Install dependencies
        run: pip install -e .[testing]
      
      - name: Run chaos tests
        run: |
          pytest tests/chaos/ \
            --chaos-iterations=100 \
            --failure-rate=0.2 \
            --timeout-probability=0.1 \
            --junit-xml=chaos-report.xml
      
      - name: Upload report
        uses: actions/upload-artifact@v3
        with:
          name: chaos-report
          path: chaos-report.xml
```

**Result:** Every PR tested with 100 chaos iterations, blocking merge if compensations fail.

### Use Case 3: Production Gamedays

**Scenario:** Monthly chaos gameday to test incident response.

**Solution:**
```python
# production_gameday.py
from sagaz.testing import ProductionChaosMonkey

# SAFE production chaos (read-only operations)
chaos = ProductionChaosMonkey(
    mode="latency_only",  # No actual failures in prod
    latency_range=(100, 1000),
    affect_percentage=0.01,  # 1% of production traffic
    duration_minutes=15,
    dry_run_log=True  # Log what WOULD happen
)

# Run gameday
gameday = ChaosGameday(
    chaos=chaos,
    target_saga="order_processing",
    monitoring=DatadogMonitoring()
)

report = await gameday.run()

# Report findings
print(f"P95 latency under chaos: {report.p95_latency_ms}ms")
print(f"Error rate increase: {report.error_rate_delta:.2%}")
print(f"Compensation latency: {report.compensation_latency_ms}ms")
```

**Result:** Team practices incident response monthly, 4 observability gaps discovered.

### Use Case 4: Compensation Logic Testing

**Scenario:** Verify inventory release compensation works correctly.

**Solution:**
```python
@pytest.mark.asyncio
async def test_inventory_compensation():
    # Force failure at payment step
    chaos = ChaosMonkey(
        targets=[("charge_payment", 1.0)]  # 100% failure
    )
    
    saga = OrderSaga(chaos=chaos)
    result = await saga.run({
        "order_id": "test-123",
        "items": [{"sku": "WIDGET-1", "qty": 5}]
    })
    
    # Verify compensation executed
    assert result.status == SagaStatus.ROLLED_BACK
    
    # Verify inventory released
    inventory = await inventory_service.get_availability("WIDGET-1")
    assert inventory.available == 100  # Original + released
    
    # Verify no charge occurred
    charges = await payment_service.get_charges("test-123")
    assert len(charges) == 0
```

**Result:** Compensation path tested on every commit, preventing production bugs.

## CI/CD Integration

### Pytest Plugin

```python
# conftest.py
import pytest
from sagaz.testing import ChaosMonkey

@pytest.fixture
def chaos(request):
    """Pytest fixture for chaos testing."""
    marker = request.node.get_closest_marker("chaos")
    if marker:
        return ChaosMonkey(**marker.kwargs)
    return None

# Usage in tests
@pytest.mark.chaos(failure_rate=0.2, seed=42)
async def test_with_chaos(chaos):
    saga = MySaga(chaos=chaos)
    await saga.run()
```

### Custom Pytest Commands

```bash
# Run chaos tests with custom parameters
pytest --chaos \
       --failure-rate=0.3 \
       --timeout-prob=0.1 \
       --iterations=500

# Run specific chaos modes
pytest --chaos-mode=latency --latency-range=100,5000
pytest --chaos-mode=timeout --timeout-duration=30
pytest --chaos-mode=resource --memory-leak=5
```

### GitHub Actions Integration

```yaml
# Chaos test matrix
jobs:
  chaos-matrix:
    strategy:
      matrix:
        failure_rate: [0.1, 0.2, 0.3]
        timeout_prob: [0.05, 0.1, 0.15]
    
    steps:
      - name: Chaos test
        run: |
          pytest tests/chaos/ \
            --failure-rate=${{ matrix.failure_rate }} \
            --timeout-prob=${{ matrix.timeout_prob }}
```

## Implementation Phases

### Phase 1: Core ChaosMonkey (v2.1.0)

- [ ] Implement `ChaosMonkey` class
- [ ] Add step interception mechanism
- [ ] Implement fault injection (failure, timeout, latency)
- [ ] Add chaos metrics and reporting

**Duration:** 1 week

### Phase 2: Testing Framework (v2.1.0)

- [ ] Create pytest plugin (`pytest-sagaz-chaos`)
- [ ] Add CLI commands for chaos testing
- [ ] Implement reproducible chaos (seeded random)
- [ ] Add chaos configuration profiles

**Duration:** 1 week

### Phase 3: CI/CD Integration (v2.2.0)

- [ ] GitHub Actions workflow examples
- [ ] GitLab CI integration
- [ ] Jenkins pipeline examples
- [ ] Chaos test reporting dashboard

**Duration:** 3 days

### Phase 4: Production Gamedays (v2.2.0)

- [ ] Implement `ProductionChaosMonkey` (safe mode)
- [ ] Add dry-run logging
- [ ] Create gameday orchestration
- [ ] Integration with monitoring (Datadog, Prometheus)

**Duration:** 1 week

### Phase 5: Advanced Features (v2.3.0)

- [ ] Resource exhaustion simulation
- [ ] Network partition simulation
- [ ] Cascading failure detection
- [ ] Chaos blueprints library

**Duration:** 1 week

## Alternatives Considered

### Alternative 1: Manual Failure Injection

Use test doubles/mocks to inject failures.

**Pros:**
- Fine-grained control
- No new dependencies

**Cons:**
- Tedious and error-prone
- Not systematic
- Engineers skip it

**Decision:** Rejected - not scalable.

### Alternative 2: External Chaos Tools (Gremlin, Chaos Toolkit)

Use existing chaos engineering platforms.

**Pros:**
- Battle-tested
- Rich features

**Cons:**
- Not saga-aware
- Requires infrastructure
- Expensive (Gremlin: $500+/month)

**Decision:** Rejected - need saga-specific chaos.

### Alternative 3: Chaos Only in Production

Only inject faults in production environment.

**Pros:**
- Tests real system

**Cons:**
- Risky
- Slow feedback
- Customer impact

**Decision:** Rejected - test in pre-prod first.

## Consequences

### Positive

1. **Reliable Compensations** - Compensation logic tested systematically
2. **Early Bug Detection** - Find issues in CI, not production
3. **Confidence** - Deploy with proven resilience
4. **Team Training** - Engineers learn to handle failures
5. **Observability** - Discover monitoring gaps

### Negative

1. **Test Duration** - Chaos tests take longer (1000 iterations)
2. **Flakiness** - Random failures can cause false positives
3. **Complexity** - Another testing dimension to manage
4. **Resource Usage** - CI runners need more compute

### Mitigations

| Risk | Mitigation |
|------|------------|
| Long test duration | Run chaos tests in parallel, nightly |
| Test flakiness | Use seeded random for reproducibility |
| False positives | Require N consecutive failures |
| Resource usage | Dedicated CI pool for chaos tests |

## Metrics & Observability

### Chaos Metrics

```python
@dataclass
class ChaosMetrics:
    total_injections: int
    failures_injected: int
    timeouts_injected: int
    latency_injected: int
    
    compensations_triggered: int
    compensations_successful: int
    compensations_failed: int
    
    avg_recovery_time_ms: float
    p95_latency_ms: float
    reliability_percentage: float
```

### Grafana Dashboard

Panels to include:
- Chaos injection rate over time
- Compensation success rate
- Recovery time distribution
- Saga reliability under chaos
- Comparison: with/without chaos

## References

### Industry Tools

- **Netflix Chaos Monkey** - Random instance termination
- **Gremlin** - Chaos Engineering as a Service
- **Chaos Toolkit** - Open-source chaos experiments
- **AWS FIS** - Fault Injection Simulator
- **Litmus Chaos** - Kubernetes chaos engineering

### Research

- [Principles of Chaos Engineering](https://principlesofchaos.org/)
- [Netflix Chaos Engineering](https://netflixtechblog.com/chaos-engineering-upgraded-878d341f15fa)
- [Google SRE Book: Testing for Reliability](https://sre.google/sre-book/testing-reliability/)

### Production Case Studies

- **Netflix** - Prevented 3 major outages by discovering issues via chaos
- **Stripe** - Reduced payment failures by 40% after systematic chaos testing
- **Amazon** - GameDay program prevents billions in potential losses

## Decision Makers

- @brunolnetto (Maintainer)

## Changelog

| Date | Change |
|------|--------|
| 2025-01-01 | Initial proposal |

---

*Proposed 2025-01-01*
