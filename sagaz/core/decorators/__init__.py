"""
Decorator API for declarative saga definitions.

Provides a user-friendly way to define sagas using decorators rather than
manual step registration. This makes saga definitions more readable and
easier to maintain.

Quick Start:
    >>> from sagaz import Saga, step, compensate
    >>>
    >>> class OrderSaga(Saga):
    ...     @step(name="create_order")
    ...     async def create_order(self, ctx):
    ...         return await OrderService.create(ctx["order_data"])
    ...
    ...     @compensate("create_order")
    ...     async def cancel_order(self, ctx):
    ...         await OrderService.delete(ctx["order_id"])
    ...
    ...     @step(name="charge_payment", depends_on=["create_order"])
    ...     async def charge(self, ctx):
    ...         return await PaymentService.charge(ctx["amount"])
    ...
    ...     @compensate("charge_payment")  # Dependencies auto-derived from action
    ...     async def refund(self, ctx):
    ...         await PaymentService.refund(ctx["charge_id"])
"""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagaz.storage.base import SagaStorage

from sagaz.core.decorators._collection import DecoratorCollectionManager
from sagaz.core.decorators._execution import ExecutionEngine
from sagaz.core.decorators._steps import (
    OnCompensateHook,
    OnEnterHook,
    OnFailureHook,
    OnSuccessHook,
    StepMetadata,
    action,
    compensate,
    forward_recovery,
    step,
)
from sagaz.core.decorators._visualization import _DecoratorVisualizationMixin
from sagaz.core.logger import get_logger
from sagaz.execution.graph import CompensationType, SagaExecutionGraph

logger = get_logger(__name__)


@dataclass
class SagaStepDefinition:
    """
    Complete definition of a saga step with its compensation.

    Used internally to track step and compensation pairs.

    Extended in v1.3.0 with pivot support.
    """

    step_id: str
    forward_fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]
    compensation_fn: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    depends_on: list[str] = field(default_factory=list)
    compensation_depends_on: list[str] = field(default_factory=list)
    compensation_type: CompensationType = CompensationType.MECHANICAL
    aggregate_type: str | None = None
    event_type: str | None = None
    timeout_seconds: float = 60.0
    compensation_timeout_seconds: float = 30.0
    max_retries: int = 3
    description: str | None = None
    # Lifecycle hooks
    on_enter: OnEnterHook | None = None
    on_success: OnSuccessHook | None = None
    on_failure: OnFailureHook | None = None
    on_compensate: OnCompensateHook | None = None
    # v1.3.0: Pivot support
    pivot: bool = False
    """If True, marks this step as a point of no return (irreversible)."""


class Saga(_DecoratorVisualizationMixin):
    """
    Base class for declarative saga definitions.

    Subclass this and use @step and @compensate decorators to define
    your saga's steps declaratively. The saga will automatically:

    - Collect all decorated methods
    - Build the execution dependency graph
    - Build the compensation dependency graph
    - Execute steps in parallel where possible
    - Compensate in correct order on failure
    - Notify all listeners of lifecycle events

    Class Attributes:
        saga_name: Optional name for the saga (used in events/metrics)
        listeners: List of SagaListener instances to notify

    Example:
        >>> from sagaz.core.listeners import LoggingSagaListener, MetricsSagaListener
        >>>
        >>> class OrderSaga(Saga):
        ...     saga_name = "order-processing"
        ...     listeners = [LoggingSagaListener(), MetricsSagaListener()]
        ...
        ...     @step(name="create_order")
        ...     async def create_order(self, ctx):
        ...         return {"order_id": "ORD-123"}
    """

    # Class-level attributes (override in subclass)
    saga_name: str | None = None
    listeners: list | None = None  # List of SagaListener instances (None = use config)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # Auto-register triggers
        # Import inside method to avoid circular imports
        from sagaz.triggers.registry import TriggerRegistry

        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if hasattr(method, "_trigger_metadata"):
                TriggerRegistry.register(cls, name, method._trigger_metadata)

    def __init__(self, name: str | None = None, config=None):
        """
        Initialize the saga.

        Supports two usage modes:

        1. Declarative (via inheritance + decorators):
            class OrderSaga(Saga):
                saga_name = "order"

                @action("step1")
                async def step1(self, ctx): return {}

            saga = OrderSaga()
            result = await saga.run({})

        2. Imperative (via instance + add_step):
            saga = Saga(name="order")
            saga.add_step("step1", action_fn, compensation_fn)
            result = await saga.run({})

        Args:
            name: Saga name (required for imperative mode, optional for declarative)
            config: Optional SagaConfig. If not provided, uses global config.

        Note: You cannot mix both approaches. Once you use decorators,
              add_step() will raise an error, and vice versa.
        """
        self._steps: list[SagaStepDefinition] = []
        self._step_registry: dict[str, SagaStepDefinition] = {}
        self._compensation_graph = SagaExecutionGraph()
        self._context: dict[str, Any] = {}
        self._saga_id: str = ""

        # Mode tracking: 'declarative', 'imperative', or None (not yet determined)
        self._mode: str | None = None

        # v1.3.0: Pivot support
        self._forward_recovery_handlers: dict[str, Any] = {}
        self._completed_pivots: set[str] = set()
        self._tainted_steps: set[str] = set()
        self._pivot_reached: bool = False

        # Use provided config or global config
        if config is not None:
            self._config = config
        else:
            from sagaz.core.config import get_config

            self._config = get_config()

        # If no class-level listeners defined, use config listeners
        if self.listeners is None and self._config:
            self._instance_listeners = self._config.listeners
        else:
            self._instance_listeners = self.listeners or []

        # Collect decorated methods (if any)
        collection_manager = DecoratorCollectionManager(self)
        collection_manager.collect_all()

        # If decorated methods were found, we're in declarative mode
        if self._steps:
            self._mode = "declarative"
            # saga_name takes precedence, then name parameter
            if self.saga_name is None and name is not None:
                self.saga_name = name
        else:
            # No decorators found - allow imperative mode
            # Name is required for imperative usage
            if name is not None:
                self.saga_name = name

    def get_pivot_steps(self) -> list[str]:
        """Get names of all pivot steps in this saga."""
        return [step.step_id for step in self._steps if step.pivot]

    def _get_taint_propagator(self):
        """Create a TaintPropagator for this saga."""
        from sagaz.execution.pivot import TaintPropagator

        step_names = {step.step_id for step in self._steps}
        dependencies = {step.step_id: set(step.depends_on) for step in self._steps}
        pivots = {step.step_id for step in self._steps if step.pivot}

        return TaintPropagator(
            step_names=step_names,
            dependencies=dependencies,
            pivots=pivots,
            completed_pivots=self._completed_pivots,
        )

    def _propagate_taint_from_pivot(self, pivot_step_id: str) -> set[str]:
        """
        Propagate taint when a pivot step completes.

        Args:
            pivot_step_id: The pivot step that just completed

        Returns:
            Set of newly tainted step names
        """
        propagator = self._get_taint_propagator()
        newly_tainted = propagator.propagate_taint(pivot_step_id)
        self._tainted_steps.update(newly_tainted)
        self._completed_pivots.add(pivot_step_id)
        self._pivot_reached = True

        if newly_tainted:
            logger.info(f"Pivot '{pivot_step_id}' completed - tainted ancestors: {newly_tainted}")

        return set(newly_tainted)

    def _is_step_tainted(self, step_id: str) -> bool:
        """Check if a step is tainted (locked from rollback)."""
        return step_id in self._tainted_steps

    # =========================================================================
    # Imperative API Support - add_step() for programmatic saga building
    # =========================================================================

    def add_step(
        self,
        name: str,
        action: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]],
        compensation: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        depends_on: list[str] | None = None,
        timeout_seconds: float = 60.0,
        compensation_timeout_seconds: float = 30.0,
        max_retries: int = 3,
        description: str | None = None,
    ) -> "Saga":
        """
        Add a step programmatically (imperative mode).

        Args:
            name: Unique step identifier
            action: Async function that takes context dict and returns updated context
            compensation: Async function to undo this step on failure
            depends_on: List of step names that must complete before this step
            timeout_seconds: Step execution timeout (default: 60s)
            compensation_timeout_seconds: Compensation timeout (default: 30s)
            max_retries: Maximum retry attempts (default: 3)
            description: Human-readable description

        Returns:
            Self for method chaining

        Raises:
            TypeError: If saga has decorated methods (declarative mode)
            ValueError: If step name already exists

        Example:
            saga = Saga(name="order-processing")
            saga.add_step("validate", validate_order)
            saga.add_step("charge", charge_payment, refund_payment, depends_on=["validate"])
            saga.add_step("ship", ship_order, depends_on=["charge"])
            result = await saga.run({"order_id": "123"})
        """
        # Check for mode conflict
        if self._mode == "declarative":
            msg = (
                "Cannot use add_step() on a saga with @action/@compensate decorators. "
                "Choose one approach: either use decorators (declarative) or "
                "add_step() (imperative), but not both. See Saga class docstring."
            )
            raise TypeError(msg)

        # Check for duplicate step name
        if name in self._step_registry:
            msg = f"Step '{name}' already exists in this saga"
            raise ValueError(msg)

        # Set mode to imperative
        self._mode = "imperative"

        # Create step definition
        step_def = SagaStepDefinition(
            step_id=name,
            forward_fn=action,
            compensation_fn=compensation,
            depends_on=depends_on or [],
            timeout_seconds=timeout_seconds,
            compensation_timeout_seconds=compensation_timeout_seconds,
            max_retries=max_retries,
            description=description or f"Execute {name}",
        )

        self._steps.append(step_def)
        self._step_registry[name] = step_def

        return self  # Enable method chaining

    def get_steps(self) -> list[SagaStepDefinition]:
        """Get all step definitions."""
        return self._steps.copy()

    def get_step(self, name: str) -> SagaStepDefinition | None:
        """Get a specific step by name."""
        return self._step_registry.get(name)

    def get_execution_order(self) -> list[list[SagaStepDefinition]]:
        """
        Compute step execution order respecting dependencies.

        Returns:
            List of levels, where steps in each level can run in parallel

        Raises:
            ValueError: If circular dependencies detected
        """
        if not self._steps:
            return []

        step_map = {s.step_id: s for s in self._steps}
        in_degree = {s.step_id: len(s.depends_on) for s in self._steps}
        remaining = set(step_map.keys())

        return self._topological_sort_steps(step_map, in_degree, remaining)

    def _topological_sort_steps(
        self, step_map: dict[str, SagaStepDefinition], in_degree: dict[str, int], remaining: set
    ) -> list[list[SagaStepDefinition]]:
        """Perform topological sort on steps."""
        levels: list[list[SagaStepDefinition]] = []

        while remaining:
            current_level = [step_map[sid] for sid in remaining if in_degree[sid] == 0]
            if not current_level:
                msg = "Circular dependency detected in saga steps"
                raise ValueError(msg)
            levels.append(current_level)
            self._update_in_degrees(current_level, remaining, step_map, in_degree)

        return levels

    def _update_in_degrees(
        self,
        current_level: list[SagaStepDefinition],
        remaining: set[str],
        step_map: dict[str, SagaStepDefinition],
        in_degree: dict[str, int],
    ) -> None:
        """Update in-degrees after processing a level."""
        for step_def in current_level:
            remaining.remove(step_def.step_id)
            for other_id in remaining:
                if step_def.step_id in step_map[other_id].depends_on:
                    in_degree[other_id] -= 1

    async def run(
        self, initial_context: dict[str, Any], saga_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute this saga.

        Args:
            initial_context: Initial data for the saga
            saga_id: Optional saga identifier for tracing

        Returns:
            Final context with all step results merged

        Raises:
            Exception: If saga fails (compensations will be attempted first)
        """
        engine = ExecutionEngine(self)
        return await engine.run(initial_context, saga_id)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(steps={len(self._steps)})"


# action and step are imported from sagaz.core._step_decorators and re-exported
# here for backwards compatibility. Do not redefine them.
__all__ = ["Saga", "SagaStepDefinition", "action", "compensate", "forward_recovery", "step"]
