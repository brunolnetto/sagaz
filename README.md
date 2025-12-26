# Sagaz - Production-Ready Saga Pattern for Python

[![codecov](https://codecov.io/gh/brunolnetto/sagaz/graph/badge.svg?token=29PU5W65KL)](https://codecov.io/gh/brunolnetto/sagaz)
[![Tests](https://github.com/brunolnetto/sagaz/actions/workflows/tests.yml/badge.svg)](https://github.com/brunolnetto/sagaz/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/sagaz.svg)](https://pypi.org/project/sagaz/)

**Enterprise-grade distributed transaction orchestration with exactly-once semantics.**


---

## 🚀 Features

### Core Saga Pattern
- ✅ **Sequential & Parallel (DAG) execution** - Optimize throughput with dependency graphs
- ✅ **Automatic compensation** - Rollback on failures with transaction safety
- ✅ **Three failure strategies** - FAIL_FAST, WAIT_ALL, FAIL_FAST_WITH_GRACE
- ✅ **Retry logic** - Exponential backoff with configurable limits
- ✅ **Timeout protection** - Per-step and global timeouts
- ✅ **Idempotency support** - Safe retries and recovery

### Transactional Outbox Pattern
- ✅ **Exactly-once delivery** - Transactional event publishing
- 🆕 **Optimistic sending** - 10x latency improvement (<10ms)
- 🆕 **Consumer inbox** - Exactly-once processing guarantee
- ✅ **Multiple brokers** - Redis Streams, Kafka, RabbitMQ, or in-memory
- ✅ **Dead letter queue** - Automatic failure handling
- ✅ **Worker auto-scaling** - Kubernetes HPA support

### Configuration & Developer Experience 🆕
- 🆕 **Unified SagaConfig** - Single config for storage, broker, observability
- 🆕 **Environment variables** - 12-factor app support via `SagaConfig.from_env()`
- 🆕 **Mermaid diagrams** - `saga.to_mermaid()` for flowchart visualization
- 🆕 **Connected graph validation** - Enforces single connected component in DAG sagas
- ✅ **Global configuration** - Configure once, all sagas inherit
- ✅ **Type-safe instances** - Real storage/broker instances, not brittle strings

### Storage Backends
- ✅ **PostgreSQL** - Production-grade with ACID guarantees
- ✅ **Redis** - High-performance caching layer
- ✅ **In-Memory** - Testing and development

### Monitoring & Operations
- ✅ **Prometheus metrics** - 40+ metrics exposed
- ✅ **OpenTelemetry tracing** - Distributed tracing support
- ✅ **Structured logging** - JSON logs with correlation IDs
- 🆕 **Grafana dashboard** - Ready-to-import JSON template
- 🆕 **Kubernetes manifests** - Production-ready deployment
- ✅ **Health checks** - Liveness and readiness probes
- 🆕 **Chaos engineering tests** - 12 resilience tests validating production readiness

---

## 📦 Installation

```bash
# Core library
pip install sagaz

# With PostgreSQL support
pip install sagaz[postgresql]

# With Kafka broker
pip install sagaz[kafka]

# All features
pip install sagaz[all]
```

---

## 🎯 Quick Start

### Basic Saga (Declarative API)

```python
from sagaz import Saga, action, compensate

class OrderSaga(Saga):
    saga_name = "order-processing"
    
    @action("reserve_inventory")
    async def reserve_inventory(self, ctx):
        inventory_id = await inventory_service.reserve(ctx["order_id"])
        return {"inventory_id": inventory_id}
    
    @compensate("reserve_inventory")
    async def release_inventory(self, ctx):
        await inventory_service.release(ctx["inventory_id"])
    
    @action("charge_payment", depends_on=["reserve_inventory"])
    async def charge_payment(self, ctx):
        return await payment_service.charge(ctx["amount"])

# Execute saga
saga = OrderSaga()
result = await saga.run({"order_id": "123", "amount": 99.99})
```

### Classic API (Imperative)

```python
from sagaz import ClassicSaga

saga = ClassicSaga(name="OrderSaga")

# These run in parallel (no dependencies)
await saga.add_step("check_inventory", check_inventory, compensate_inventory, dependencies=set())
await saga.add_step("validate_address", validate_address, None, dependencies=set())

# This waits for both
await saga.add_step(
    "reserve_items",
    reserve_items,
    release_items,
    dependencies={"check_inventory", "validate_address"}
)

result = await saga.execute()
```

### Transactional Outbox + Optimistic Sending 🆕

```python
from sagaz.outbox import OptimisticPublisher, OutboxWorker
from sagaz.outbox.storage import PostgreSQLOutboxStorage
from sagaz.outbox.brokers import KafkaBroker

# Setup
storage = PostgreSQLOutboxStorage("postgresql://localhost/db")
broker = KafkaBroker(bootstrap_servers="localhost:9092")
publisher = OptimisticPublisher(storage, broker, enabled=True)

# Publish event transactionally
async with db.transaction():
    await saga_storage.save(saga)
    await outbox_storage.insert(event)
    # Transaction committed

# Immediate publish (< 10ms) 🔥
await publisher.publish_after_commit(event)
# Falls back to worker if fails
```

### Consumer Inbox (Exactly-Once) 🆕

```python
from sagaz.outbox import ConsumerInbox

inbox = ConsumerInbox(storage, consumer_name="order-service")

async def process_order(payload: dict):
    order = await create_order(payload)
    return {"order_id": order.id}

# Exactly-once processing - duplicates automatically skipped
result = await inbox.process_idempotent(
    event_id=msg.headers['message_id'],
    source_topic=msg.topic,
    event_type="OrderCreated",
    payload=msg.value,
    handler=process_order
)
```

### Unified Configuration 🆕

```python
from sagaz import SagaConfig, configure

# One config for everything
config = SagaConfig(
    storage=PostgreSQLSagaStorage("postgresql://localhost/db"),
    broker=KafkaBroker(bootstrap_servers="localhost:9092"),
    metrics=True,
    tracing=True,
    logging=True,
)
configure(config)  # All sagas now inherit this config!

# Or from environment variables (12-factor app)
config = SagaConfig.from_env()  # Reads SAGAZ_STORAGE_URL, SAGAZ_BROKER_URL, etc.
```

### Mermaid Diagram Visualization 🆕

```python
from sagaz import Saga, action, compensate

class OrderSaga(Saga):
    saga_name = "order"
    
    @action("reserve")
    async def reserve(self, ctx): return {}
    
    @compensate("reserve")
    async def release(self, ctx): pass
    
    @action("charge", depends_on=["reserve"])
    async def charge(self, ctx): return {}
    
    @compensate("charge")
    async def refund(self, ctx): pass

saga = OrderSaga()

# Generate Mermaid diagram with state markers
print(saga.to_mermaid())

# Visualize specific execution from storage
diagram = await saga.to_mermaid_with_execution(
    saga_id="abc-123",
    storage=PostgreSQLSagaStorage(...)
)
```

**Output:** State machine diagram with ● START, ◎ SUCCESS/ROLLED_BACK, color-coded paths (green=success, amber=compensation, red=failure), and execution trail highlighting.

---

## ☸️ Kubernetes Deployment

```bash
# One-command deployment
kubectl create namespace sagaz
kubectl apply -f k8s/

# Deployed components:
# - PostgreSQL StatefulSet (20Gi persistent storage)
# - Outbox Worker Deployment (3-10 replicas with HPA)
# - Prometheus ServiceMonitor + 8 Alert Rules
# - Database Migration Job
```

**Features:**
- Auto-scaling based on pending events
- Zero-downtime rolling updates
- Built-in health checks
- Production security (non-root, read-only fs)
- Complete monitoring stack

See [`k8s/README.md`](k8s/README.md) for detailed deployment guide.

---

## 📊 Monitoring

### Prometheus Metrics

```python
# Saga metrics
saga_execution_total{status}
saga_execution_duration_seconds
saga_step_duration_seconds{step_name}

# Outbox metrics
outbox_pending_events_total
outbox_published_events_total
outbox_optimistic_send_success_total  # 🆕
consumer_inbox_duplicates_total       # 🆕
```

### Grafana Dashboard 🆕

Ready-to-import dashboard template at [`grafana/sagaz-dashboard.json`](grafana/sagaz-dashboard.json).

### Grafana Alerts

- **OutboxHighLag** - >5000 pending events for 10min
- **OutboxWorkerDown** - No workers running
- **OutboxHighErrorRate** - >1% publish failures
- **OptimisticSendHighFailureRate** - >10% optimistic failures 🆕

---

## 💥 Chaos Engineering

**Production readiness validated through deliberate failure injection.**

The library includes comprehensive chaos engineering tests that verify system resilience:

### Test Categories

- ✅ **Worker Crash Recovery** - Workers can recover from crashes, no data loss
- ✅ **Database Connection Loss** - Graceful handling of DB failures with retry
- ✅ **Broker Downtime** - Messages not lost when broker unavailable
- ✅ **Network Partitions** - No duplicate processing under split-brain
- ✅ **Concurrent Failures** - System recovers from multiple simultaneous failures
- ✅ **Data Consistency** - Exactly-once guarantees maintained under chaos

### Run Chaos Tests

```bash
# Run all chaos engineering tests
pytest tests/test_chaos_engineering.py -v -m chaos

# Test specific failure scenario
pytest tests/test_chaos_engineering.py::TestWorkerCrashRecovery -v
```

**Key Findings:**
- ✅ No data loss even with 30% random failure rate
- ✅ Exactly-once processing with 5 concurrent workers
- ✅ Graceful handling of 50 events under extreme load
- ✅ Automatic recovery with exponential backoff

See [docs/CHAOS_ENGINEERING.md](docs/CHAOS_ENGINEERING.md) for detailed chaos test documentation.

---

## 📚 Documentation

| Topic | Link |
|-------|------|
| **Documentation Index** | [docs/DOCUMENTATION_INDEX.md](docs/DOCUMENTATION_INDEX.md) |
| **Configuration Guide** 🆕 | [docs/guides/configuration.md](docs/guides/configuration.md) |
| **DAG Pattern** | [docs/feature_compensation_graph.md](docs/feature_compensation_graph.md) |
| **Optimistic Sending** 🆕 | [docs/optimistic-sending.md](docs/optimistic-sending.md) |
| **Consumer Inbox** 🆕 | [docs/consumer-inbox.md](docs/consumer-inbox.md) |
| **Kubernetes Deploy** 🆕 | [k8s/README.md](k8s/README.md) |
| **Grafana Dashboards** 🆕 | [grafana/README.md](grafana/README.md) |
| **Chaos Engineering** 🆕 | [docs/CHAOS_ENGINEERING.md](docs/CHAOS_ENGINEERING.md) |
| **Changelog** | [docs/development/changelog.md](docs/development/changelog.md) |

---

## 📈 Performance

| Operation | Latency | Improvement |
|-----------|---------|-------------|
| Saga execution | ~50ms | Baseline |
| Outbox polling | ~100ms | Baseline |
| **Optimistic publish** 🆕 | **<10ms** | **10x faster** ⚡ |
| Inbox dedup check | <1ms | Sub-millisecond |

**Tested on:**
- PostgreSQL 16
- Kafka 3.x
- 4 CPU cores, 8GB RAM

---

## 🏆 Production Stats

- ✅ **96% test coverage** (860+ passing tests)
- ✅ **Type-safe** - Full type hints
- ✅ **Zero dependencies** - Core features work standalone
- ✅ **Well-documented** - Comprehensive examples
- ✅ **Battle-tested** - Production-ready
- 🆕 **Kubernetes-native** - Cloud-ready deployment
- 🆕 **Mermaid visualization** - Auto-generated saga diagrams

---

## 🧪 Development

```bash
# Clone repository
git clone https://github.com/brunolnetto/sagaz.git
cd sagaz

# Install dependencies (using uv)
uv sync --all-extras

# Run tests
uv run pytest

# With coverage
uv run pytest --cov=sagaz --cov-report=html
# Current: 96% coverage
```

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---

## 🔗 Project Status

**Current Version**: 1.0.3 (December 2024)

**Recent Updates** (v1.0.3):
- 🆕 Mermaid diagram generation with state markers (●/◎)
- 🆕 `to_mermaid_with_execution()` - Auto-fetch trail from storage
- 🆕 Connected graph validation for DAG sagas
- 🆕 Grafana dashboard template
- 🆕 Unified SagaConfig with environment variable support

**v1.0.0-1.0.2:**
- ✅ Optimistic sending pattern (10x latency improvement)
- ✅ Consumer inbox pattern (exactly-once processing)
- ✅ Kubernetes manifests (production deployment)
- ✅ 96% test coverage with 860+ tests

See [docs/ROADMAP.md](docs/ROADMAP.md) for roadmap.

---

**Need Help?**

- 📖 Read the [docs](docs/)
- 🐛 Report [issues](https://github.com/yourusername/sage/issues)
- 💬 Join discussions
- 📧 Contact maintainers

---

*Built with ❤️ for distributed systems*
