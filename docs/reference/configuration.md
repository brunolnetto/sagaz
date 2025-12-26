# Configuration Reference

Complete reference of all configuration options for Sagaz.

## Environment Variables

### Database

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | **Required** | `postgresql://user:pass@host:5432/db` |

### Broker

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `BROKER_TYPE` | Broker type | `kafka` | `kafka`, `rabbitmq` |
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka brokers | - | `kafka:9092` |
| `KAFKA_TOPIC` | Kafka topic | `saga-events` | `my-events` |
| `RABBITMQ_URL` | RabbitMQ connection | - | `amqp://user:pass@host:5672/` |
| `RABBITMQ_EXCHANGE` | RabbitMQ exchange | `saga-events` | `my-exchange` |

### Worker

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `WORKER_ID` | Unique worker identifier | Auto-generated | `worker-001` |
| `BATCH_SIZE` | Events per batch | `100` | `500` |
| `POLL_INTERVAL` | Seconds between polls | `1.0` | `0.5` |
| `MAX_RETRIES` | Max publish retries | `5` | `10` |

### Logging

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `LOG_LEVEL` | Logging level | `INFO` | `DEBUG`, `WARNING` |
| `LOG_FORMAT` | Log format | `text` | `json` |

### Observability

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `METRICS_PORT` | Prometheus metrics port | `8000` | `9090` |
| `OTEL_ENABLED` | Enable OpenTelemetry | `false` | `true` |
| `OTEL_SERVICE_NAME` | Service name | `sagaz-outbox-worker` | `my-worker` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP endpoint | - | `http://jaeger:4318` |

---

## Kubernetes ConfigMap

Default configuration in `k8s/configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: outbox-worker-config
  namespace:sagaz
data:
  # Worker configuration
  WORKER_BATCH_SIZE: "100"
  WORKER_POLL_INTERVAL_SECONDS: "1.0"
  WORKER_TIMEOUT_SECONDS: "30.0"
  
  # Retry configuration
  MAX_RETRY_ATTEMPTS: "10"
  INITIAL_RETRY_DELAY_SECONDS: "2"
  MAX_RETRY_DELAY_SECONDS: "3600"
  
  # Stuck claim timeout
  STUCK_CLAIM_TIMEOUT_SECONDS: "300"
  
  # Optimistic sending
  ENABLE_OPTIMISTIC_SEND: "true"
  OPTIMISTIC_SEND_TIMEOUT_SECONDS: "0.5"
  
  # Logging
  LOG_LEVEL: "INFO"
  LOG_FORMAT: "json"
  
  # Metrics
  METRICS_PORT: "8000"
  METRICS_PATH: "/metrics"
  
  # Health checks
  HEALTH_PORT: "8000"
  HEALTH_LIVE_PATH: "/health/live"
  HEALTH_READY_PATH: "/health/ready"
```

---

## Python Configuration

### OutboxConfig

```python
from sagaz.outbox.types import OutboxConfig

config = OutboxConfig(
    batch_size=100,              # Events per batch
    poll_interval_seconds=1.0,    # Poll frequency
    max_retries=5,               # Max publish retries
    claim_timeout_seconds=300,   # Stuck claim timeout
)
```

### KafkaBrokerConfig

```python
from sagaz.outbox.brokers.kafka import KafkaBrokerConfig

config = KafkaBrokerConfig(
    bootstrap_servers="kafka:9092",
    topic="saga-events",
    acks="all",                  # Wait for all replicas
    compression_type="gzip",     # Compress messages
    batch_size=16384,            # Batch size in bytes
    linger_ms=5,                 # Batch wait time
)
```

### RabbitMQBrokerConfig

```python
from sagaz.outbox.brokers.rabbitmq import RabbitMQBrokerConfig

config = RabbitMQBrokerConfig(
    url="amqp://user:pass@localhost:5672/",
    exchange_name="saga-events",
    exchange_type="topic",       # topic, direct, fanout
    durable=True,                # Survive broker restart
    delivery_mode=2,             # Persistent messages
)
```

---

## Resource Limits

### Kubernetes Resources

```yaml
resources:
  requests:
    cpu: "200m"
    memory: "256Mi"
  limits:
    cpu: "1000m"
    memory: "1Gi"
```

### Connection Pool Sizing

| Deployment Size | DB Pool | Workers |
|-----------------|---------|---------|
| Small (dev) | 5-10 | 3 |
| Medium | 20-30 | 10 |
| Large | 50-100 | 20+ |

---

## Tuning for Throughput

### High Throughput

```yaml
# configmap.yaml
data:
  WORKER_BATCH_SIZE: "500"
  WORKER_POLL_INTERVAL_SECONDS: "0.5"
```

### Low Latency

```yaml
data:
  WORKER_BATCH_SIZE: "10"
  WORKER_POLL_INTERVAL_SECONDS: "0.1"
```

### Resource Conservation

```yaml
data:
  WORKER_BATCH_SIZE: "50"
  WORKER_POLL_INTERVAL_SECONDS: "5.0"
```

---

## Prometheus Metrics

Exposed at `/metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `outbox_events_processed_total` | Counter | Total events processed |
| `outbox_events_failed_total` | Counter | Total events failed |
| `outbox_events_dead_lettered_total` | Counter | Events in dead letter |
| `outbox_batch_size` | Histogram | Batch sizes |
| `outbox_publish_duration_seconds` | Histogram | Publish latency |
| `outbox_pending_events` | Gauge | Current pending count |

---

## Related

- [Kubernetes Deployment](../guides/kubernetes.md)
- [Benchmarking Guide](../guides/benchmarking.md)
- [Architecture Overview](../architecture/overview.md)
