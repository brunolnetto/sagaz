#sagaz Documentation

> Production-ready Saga Pattern library with Transactional Outbox support

## Quick Links

| I want to... | Go to |
|-------------|-------|
| **Get started quickly** | [Quickstart Guide](quickstart.md) |
| **Understand the architecture** | [Architecture Overview](architecture/overview.md) |
| **See how data flows** | [Dataflow & Events](architecture/dataflow.md) |
| **Deploy to Kubernetes** | [Kubernetes Guide](guides/kubernetes.md) |
| **Run benchmarks** | [Benchmarking Guide](guides/benchmarking.md) |
| **See what's planned** | [Roadmap](ROADMAP.md) |

---

## Documentation Structure

```
docs/
├── quickstart.md              # 5-minute setup
├── architecture/              # System design
│   ├── overview.md            # High-level architecture
│   ├── components.md          # Service artifacts & classes
│   ├── dataflow.md            # Event flow & state machines
│   └── decisions.md           # Architecture Decision Records
├── guides/                    # How-to guides
│   ├── saga-pattern.md        # Using the Saga pattern
│   ├── outbox-pattern.md      # Transactional outbox
│   ├── kubernetes.md          # K8s deployment
│   └── benchmarking.md        # Performance testing
├── reference/                 # Technical reference
│   ├── api.md                 # API documentation
│   └── configuration.md       # Configuration options
└── archive/                   # Historical documentation
```

---

## Key Concepts

### The Saga Pattern

A Saga is a sequence of local transactions where each step has a compensating action. If any step fails, the saga executes compensations in reverse order.

```
Step 1 → Step 2 → Step 3 → ... → Complete
   ↓        ↓        ↓
Comp 1 ← Comp 2 ← Comp 3 ← ... ← Failure
```

### Transactional Outbox

Ensures exactly-once event delivery by storing events in the database within the same transaction as business data, then publishing asynchronously.

```
[Business Logic] → [DB Transaction] → [Outbox Table] → [Worker] → [Broker]
```

---

## Performance

| Metric | Local (kind) | Production Target |
|--------|-------------|-------------------|
| Insert Rate | 1,800/sec | 10,000+/sec |
| Process Rate | 1,265/sec | 5,000+/sec |
| Latency (p99) | <100ms | <50ms |

See [Benchmarking Guide](guides/benchmarking.md) for details.
