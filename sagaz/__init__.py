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
from sagaz.types import ParallelFailureStrategy, SagaResult, SagaStatus, SagaStepStatus

# =============================================================================
# Pivot/Irreversible Steps (v1.3.0)
# =============================================================================
from sagaz.pivot import (
    RecoveryAction,
    StepZone,
    SagaZones,
    PivotInfo,
    TaintPropagator,
)


__all__ = [
    # =========================================================================
    # Primary Exports (Recommended API)
    # =========================================================================
    "Saga",
    "action",
    "compensate",
    "forward_recovery",
    "SagaConfig",
    "configure",
    "get_config",

    
    # =========================================================================
    # Execution Graph
    # =========================================================================
    "SagaExecutionGraph",
    "SagaCompensationContext",
    "CompensationNode",
    "CompensationResult",
    "CompensationType",
    "CompensationFailureStrategy",
    
    # =========================================================================
    # Listeners
    # =========================================================================
    "SagaListener",
    "LoggingSagaListener",
    "MetricsSagaListener",
    "OutboxSagaListener",
    "TracingSagaListener",
    "default_listeners",
    
    # =========================================================================
    # Types and Results
    # =========================================================================
    "SagaResult",
    "SagaStatus",
    "SagaStepStatus",
    "SagaStep",
    "SagaStepDefinition",
    "SagaContext",
    "ParallelFailureStrategy",
    
    # =========================================================================
    # Pivot/Irreversible Steps (v1.3.0)
    # =========================================================================
    "RecoveryAction",
    "StepZone",
    "SagaZones",
    "PivotInfo",
    "TaintPropagator",
    
    # =========================================================================
    # Exceptions
    # =========================================================================
    "SagaError",
    "SagaExecutionError",
    "SagaCompensationError",
    "SagaStepError",
    "SagaTimeoutError",
    "MissingDependencyError",
    "CircularDependencyError",
    "CompensationGraphError",
    
    # =========================================================================
    # Orchestrator
    # =========================================================================
    "SagaOrchestrator",
]

