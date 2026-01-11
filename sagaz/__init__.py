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
    >>> from sagaz.core.listeners import MetricsSagaListener, OutboxSagaListener
    >>>
    >>> class OrderSaga(Saga):
    ...     saga_name = "order-processing"
    ...     listeners = [MetricsSagaListener(), OutboxSagaListener(storage)]

Note: You cannot mix both approaches. Once you use decorators,
      add_step() will raise an error, and vice versa.
"""

# =============================================================================
# Configuration
# =============================================================================
from sagaz.core.config import SagaConfig, configure, get_config
from sagaz.core.decorators import (
    Saga,
    SagaStepDefinition,
    action,
    compensate,
    forward_recovery,
)

# =============================================================================
# Exceptions
# =============================================================================
from sagaz.core.exceptions import (
    IdempotencyKeyRequiredError,
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
from sagaz.core.listeners import (
    LoggingSagaListener,
    MetricsSagaListener,
    OutboxSagaListener,
    SagaListener,
    TracingSagaListener,
    default_listeners,
)

# =============================================================================
# Core Saga Classes
# =============================================================================
from sagaz.core.saga import SagaContext, SagaStep
from sagaz.core.types import ParallelFailureStrategy, SagaResult, SagaStatus, SagaStepStatus

# =============================================================================
# Execution Graph (compensation and dependency management)
# =============================================================================
from sagaz.execution.graph import (
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
# Dry-Run Mode (ADR-019, v1.3.0)
# =============================================================================
from sagaz.dry_run import (
    DryRunEngine,
    DryRunMode,
    DryRunResult,
    DryRunTraceEvent,
    EstimateResult,
    SimulationResult,
    TraceResult,
    ValidationResult,
)

# =============================================================================
# Orchestrator and Types
# =============================================================================
from sagaz.execution.orchestrator import SagaOrchestrator

# =============================================================================
# Pivot/Irreversible Steps (v1.3.0)
# =============================================================================
from sagaz.execution.pivot import (
    PivotInfo,
    RecoveryAction,
    SagaZones,
    StepZone,
    TaintPropagator,
)

__all__ = [
    "CircularDependencyError",
    "CompensationFailureStrategy",
    "CompensationGraphError",
    "CompensationNode",
    "CompensationResult",
    "CompensationType",
    # =========================================================================
    # Dry-Run Mode (ADR-019, v1.3.0)
    # =========================================================================
    "DryRunEngine",
    "DryRunMode",
    "DryRunResult",
    "DryRunTraceEvent",
    "EstimateResult",
    # =========================================================================
    # Exceptions
    # =========================================================================
    "IdempotencyKeyRequiredError",
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
    "SimulationResult",
    "StepZone",
    "TaintPropagator",
    "TracingSagaListener",
    "TraceResult",
    "ValidationResult",
    "action",
    "compensate",
    "configure",
    "default_listeners",
    "forward_recovery",
    "get_config",
]


# =============================================================================
# Backward Compatibility Aliases
# =============================================================================
# These imports allow existing code using the old module paths to continue working.
# For example: `from sagaz.core.config import SagaConfig` will still work.

# Re-export cli_examples for backward compatibility
from sagaz.cli import examples as cli_examples
