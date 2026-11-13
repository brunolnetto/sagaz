# Observability demonstrations

## `otel_tracing` — OpenTelemetry spans for saga execution

```bash
pip install 'sagaz[tracing]'
sagaz demo run otel_tracing
```

Attaches `TracingSagaListener` to an order saga (`reserve_stock → charge_card → ship_order`)
and runs it twice. Spans go to an in-memory exporter that stands in for an OTLP collector,
so no infrastructure is needed.

```text
▶ checkout o-1001 (carrier up): completed
  saga.execute.order-checkout  [OK]
    └─ saga.step.action.reserve_stock  [OK]
    └─ saga.step.action.charge_card  [OK]
    └─ saga.step.action.ship_order  [OK]

▶ checkout o-1002 (carrier down): rolled_back
  saga.execute.order-checkout  [ERROR]
    └─ saga.step.action.reserve_stock  [OK]
    └─ saga.step.action.charge_card  [OK]
    └─ saga.step.action.ship_order  [ERROR]
    └─ saga.step.compensation.charge_card  [OK]
    └─ saga.step.compensation.reserve_stock  [OK]
```

### Span model

| Span | Parent | Key attributes |
|------|--------|----------------|
| `saga.execute.<saga_name>` | caller's span, if any | `saga.id`, `saga.name`, `saga.total_steps`, `saga.service`, `saga.status` (`completed` / `rolled_back`) |
| `saga.step.action.<step>` | saga span | `saga.id`, `saga.name`, `saga.step.name`, `saga.step.type=action` |
| `saga.step.compensation.<step>` | saga span | same, with `saga.step.type=compensation` |

A failing step and a failed saga get status `ERROR` and an `exception` event with the error.

### Using it in your service

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from sagaz import Saga
from sagaz.core.listeners import TracingSagaListener
from sagaz.observability.monitoring.tracing import SagaTracer

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="collector:4317")))
trace.set_tracer_provider(provider)


class OrderSaga(Saga):
    listeners = [TracingSagaListener(tracer=SagaTracer("order-service"))]
```

One listener instance can trace concurrent runs of the same saga class: spans are keyed by
each run's context. Without OpenTelemetry installed, the listener is a no-op.
