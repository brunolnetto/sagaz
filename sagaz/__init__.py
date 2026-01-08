# ============================================
# FILE: sagaz/__init__.py
# ============================================

"""
Sagaz - Enterprise Saga Pattern Implementation

A production-ready implementation of the Saga pattern for distributed transactions
with support for:
- Declarative saga definitions with @action and @compensate decorators
- Imperative saga building with add_step() method chaining
- Flexible compensation ordering with dependency graphs
- Multiple storage backends (Memory, Redis, PostgreSQL)
- OpenTelemetry distributed tracing
- Prometheus metrics
- Saga lifecycle listeners for cross-cutting concerns

Usage Mode 1 - Declarative (via inheritance + decorators):
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

Usage Mode 2 - Imperative (via instance + add_step):
    >>> from sagaz import Saga
    >>>
    >>> saga = Saga(name="order-processing")
    >>> saga.add_step("create_order", create_order, cancel_order)
    >>> saga.add_step("charge", charge_payment, refund, depends_on=["create_order"])
    >>> result = await saga.run({"order_id": "123"})

With Listeners (Metrics, Logging, Outbox):
    >>> from sagaz.listeners import MetricsSagaListener, OutboxSagaListener
    >>>
    >>> class OrderSaga(Saga):
    ...     saga_name = "order-processing"
    ...     listeners = [MetricsSagaListener(), OutboxSagaListener(storage)]

Note: You cannot mix both approaches. Once you use decorators,
      add_step() will raise an error, and vice versa.
"""

# =============================================================================
# Execution Graph (compensation and dependency management)
# =============================================================================
# =============================================================================
# Configuration
# =============================================================================
from sagaz.config import SagaConfig, configure, get_config

# =============================================================================
# Core Saga Classes
# =============================================================================
from sagaz.core import SagaContext, SagaStep
from sagaz.decorators import (
    Saga,
    SagaStepDefinition,
    action,
    compensate,
    forward_recovery,
)

# =============================================================================
# Exceptions
# =============================================================================
from sagaz.exceptions import (
    MissingDependencyError,
    SagaCompensationError,
    SagaError,
    SagaExecutionError,
    SagaStepError,
    SagaTimeoutError,
)
from sagaz.execution_graph import (
    CircularDependencyError,
    CompensationFailureStrategy,
    CompensationGraphError,
    CompensationNode,
    CompensationResult,
    CompensationType,
    SagaCompensationContext,
    SagaExecutionGraph,
)

# =============================================================================
# Listeners (observability and side effects)
# =============================================================================
from sagaz.listeners import (
    LoggingSagaListener,
    MetricsSagaListener,
    OutboxSagaListener,
    SagaListener,
    TracingSagaListener,
    default_listeners,
)

# =============================================================================
# Orchestrator and Types
# =============================================================================
from sagaz.orchestrator import SagaOrchestrator

# =============================================================================
# Pivot/Irreversible Steps (v1.3.0)
# =============================================================================
from sagaz.pivot import (
    PivotInfo,
    RecoveryAction,
    SagaZones,
    StepZone,
    TaintPropagator,
)
from sagaz.types import ParallelFailureStrategy, SagaResult, SagaStatus, SagaStepStatus

__all__ = [
    "CircularDependencyError",
    "CompensationFailureStrategy",
    "CompensationGraphError",
    "CompensationNode",
    "CompensationResult",
    "CompensationType",
    "LoggingSagaListener",
    "MetricsSagaListener",
    "MissingDependencyError",
    "OutboxSagaListener",
    "ParallelFailureStrategy",
    "PivotInfo",
    # =========================================================================
    # Pivot/Irreversible Steps (v1.3.0)
    # =========================================================================
    "RecoveryAction",
    # =========================================================================
    # Primary Exports (Recommended API)
    # =========================================================================
    "Saga",
    "SagaCompensationContext",
    "SagaCompensationError",
    "SagaConfig",
    "SagaContext",
    # =========================================================================
    # Exceptions
    # =========================================================================
    "SagaError",
    "SagaExecutionError",
    # =========================================================================
    # Execution Graph
    # =========================================================================
    "SagaExecutionGraph",
    # =========================================================================
    # Listeners
    # =========================================================================
    "SagaListener",
    # =========================================================================
    # Orchestrator
    # =========================================================================
    "SagaOrchestrator",
    # =========================================================================
    # Types and Results
    # =========================================================================
    "SagaResult",
    "SagaStatus",
    "SagaStep",
    "SagaStepDefinition",
    "SagaStepError",
    "SagaStepStatus",
    "SagaTimeoutError",
    "SagaZones",
    "StepZone",
    "TaintPropagator",
    "TracingSagaListener",
    "action",
    "compensate",
    "configure",
    "default_listeners",
    "forward_recovery",
    "get_config",
]

