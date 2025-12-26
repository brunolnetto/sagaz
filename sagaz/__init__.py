# ============================================
# FILE: sagaz/__init__.py
# ============================================

"""
Sagaz - Enterprise Saga Pattern Implementation

A production-ready implementation of the Saga pattern for distributed transactions
with support for:
- Declarative saga definitions with @action and @compensate decorators
- Flexible compensation ordering with dependency graphs
- Multiple storage backends (Memory, Redis, PostgreSQL)
- OpenTelemetry distributed tracing
- Prometheus metrics
- Saga lifecycle listeners for cross-cutting concerns

Quick Start (Declarative API - Recommended):
    >>> from sagaz import Saga, action, compensate
    >>>
    >>> class OrderSaga(Saga):
    ...     saga_name = "order-processing"
    ...
    ...     @action("create_order")
    ...     async def create_order(self, ctx):
    ...         return await OrderService.create(ctx)
    ...
    ...     @compensate("create_order")
    ...     async def cancel_order(self, ctx):
    ...         await OrderService.delete(ctx["order_id"])
    >>>
    >>> saga = OrderSaga()
    >>> result = await saga.run({"items": [...], "amount": 99.99})

With Listeners (Metrics, Logging, Outbox):
    >>> from sagaz.listeners import MetricsSagaListener, OutboxSagaListener
    >>>
    >>> class OrderSaga(Saga):
    ...     saga_name = "order-processing"
    ...     listeners = [MetricsSagaListener(), OutboxSagaListener(storage)]

Classic API (Imperative):
    >>> from sagaz import ClassicSaga
    >>>
    >>> saga = ClassicSaga(name="OrderSaga")
    >>> saga.add_step("create_order", create_order, compensate=cancel_order)
    >>> result = await saga.execute(context={"order_id": "123"})
"""

# Import the classic imperative Saga as ClassicSaga
from sagaz.compensation_graph import (
    CircularDependencyError,
    CompensationGraphError,
    CompensationNode,
    CompensationType,
    SagaCompensationGraph,
)

# Configuration
from sagaz.config import SagaConfig, configure, get_config
from sagaz.core import Saga as ClassicSaga
from sagaz.core import SagaContext, SagaStep

# Import the declarative Saga as the primary Saga class
from sagaz.decorators import (
    DeclarativeSaga,  # Backward compatibility alias
    Saga,
    SagaStepDefinition,
    action,  # Preferred terminology
    compensate,
    step,  # Alias for backward compatibility
)
from sagaz.exceptions import (
    MissingDependencyError,
    SagaCompensationError,
    SagaError,
    SagaExecutionError,
    SagaStepError,
    SagaTimeoutError,
)

# Import listeners
from sagaz.listeners import (
    LoggingSagaListener,
    MetricsSagaListener,
    OutboxSagaListener,
    SagaListener,
    TracingSagaListener,
    default_listeners,
)
from sagaz.orchestrator import SagaOrchestrator
from sagaz.types import ParallelFailureStrategy, SagaResult, SagaStatus, SagaStepStatus

# Backward compatibility aliases
DAGSaga = ClassicSaga


__all__ = [
    "CircularDependencyError",
    "ClassicSaga",
    "CompensationGraphError",
    "CompensationNode",
    "CompensationType",
    "DAGSaga",
    "DeclarativeSaga",
    "LoggingSagaListener",
    "MetricsSagaListener",
    "MissingDependencyError",
    "OutboxSagaListener",
    "ParallelFailureStrategy",
    "Saga",
    "SagaCompensationError",
    "SagaCompensationGraph",
    "SagaConfig",
    "SagaContext",
    "SagaError",
    "SagaExecutionError",
    "SagaListener",
    "SagaOrchestrator",
    "SagaResult",
    "SagaStatus",
    "SagaStep",
    "SagaStepDefinition",
    "SagaStepError",
    "SagaStepStatus",
    "SagaTimeoutError",
    "TracingSagaListener",
    "action",
    "compensate",
    "configure",
    "default_listeners",
    "get_config",
    "step",
]
