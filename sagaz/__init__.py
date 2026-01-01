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

from sagaz.compensation_graph import (
    CircularDependencyError,
    CompensationFailureStrategy,
    CompensationGraphError,
    CompensationNode,
    CompensationResult,
    CompensationType,
    SagaCompensationContext,
    SagaCompensationGraph,  # Backward compatibility alias
    SagaExecutionGraph,
)

# Configuration
from sagaz.config import SagaConfig, configure, get_config

# Legacy ClassicSaga for backward compatibility (deprecated)
from sagaz.core import Saga as ClassicSaga
from sagaz.core import SagaContext, SagaStep

# The unified Saga class (primary export)
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

# Backward compatibility aliases (deprecated - use Saga instead)
# DAGSaga must remain as ClassicSaga for backward compatibility with tests
DAGSaga = ClassicSaga


__all__ = [
    "CircularDependencyError",
    # Legacy/internal (for backward compatibility)
    "ClassicSaga",  # Deprecated - use Saga instead
    "CompensationFailureStrategy",
    "CompensationGraphError",
    "CompensationNode",
    "CompensationResult",
    "CompensationType",
    "DAGSaga",  # Deprecated - use Saga instead
    "DeclarativeSaga",  # Deprecated - use Saga instead
    "LoggingSagaListener",
    "MetricsSagaListener",
    "MissingDependencyError",
    "OutboxSagaListener",
    "ParallelFailureStrategy",
    # Primary exports
    "Saga",
    "SagaCompensationContext",
    "SagaCompensationError",
    # Compensation/Execution graph
    "SagaCompensationGraph",  # Backward compatibility alias
    # Configuration
    "SagaConfig",
    "SagaContext",
    # Exceptions
    "SagaError",
    "SagaExecutionError",
    "SagaExecutionGraph",
    # Listeners
    "SagaListener",
    # Orchestrator
    "SagaOrchestrator",
    # Types and results
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
