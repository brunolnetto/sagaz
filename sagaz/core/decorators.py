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

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:  # pragma: no cover
    from sagaz.storage.base import SagaStorage


from sagaz.core.logger import get_logger
from sagaz.core.types import SagaStatus
from sagaz.execution.graph import CompensationType, SagaExecutionGraph

logger = get_logger(__name__)

# Type for saga step functions
F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

# Hook type definitions
OnEnterHook = Callable[[dict[str, Any], str], Awaitable[None] | None]
OnSuccessHook = Callable[[dict[str, Any], str, Any], Awaitable[None] | None]
OnFailureHook = Callable[[dict[str, Any], str, Exception], Awaitable[None] | None]
OnCompensateHook = Callable[[dict[str, Any], str], Awaitable[None] | None]


@dataclass
class StepMetadata:
    """Metadata attached to step functions via decorator."""

    name: str
    depends_on: list[str] = field(default_factory=list)
    aggregate_type: str | None = None
    event_type: str | None = None
    timeout_seconds: float = 60.0
    max_retries: int = 3
    description: str | None = None
    # Lifecycle hooks
    on_enter: OnEnterHook | None = None
    on_success: OnSuccessHook | None = None
    on_failure: OnFailureHook | None = None
    # v1.3.0: Pivot support
    pivot: bool = False
    """If True, marks this step as a point of no return (irreversible)."""


@dataclass
class CompensationMetadata:
    """Metadata attached to compensation functions via decorator."""

    for_step: str
    depends_on: list[str] = field(default_factory=list)
    compensation_type: CompensationType = CompensationType.MECHANICAL
    timeout_seconds: float = 30.0
    max_retries: int = 3
    description: str | None = None
    # Lifecycle hook for compensation
    on_compensate: OnCompensateHook | None = None


def step(
    name: str,
    depends_on: list[str] | None = None,
    aggregate_type: str | None = None,
    event_type: str | None = None,
    timeout_seconds: float = 60.0,
    max_retries: int = 3,
    description: str | None = None,
    on_enter: OnEnterHook | None = None,
    on_success: OnSuccessHook | None = None,
    on_failure: OnFailureHook | None = None,
    pivot: bool = False,
) -> Callable[[F], F]:
    """
    Decorator to mark a method as a saga step.

    Args:
        name: Unique identifier for this step
        depends_on: List of step names that must complete before this step
        aggregate_type: Event aggregate type (for outbox pattern)
        event_type: Event type (for outbox pattern)
        timeout_seconds: Step execution timeout (default: 60s)
        max_retries: Maximum retry attempts (default: 3)
        description: Human-readable description
        on_enter: Hook called before step execution (ctx, step_name) -> None
        on_success: Hook called after success (ctx, step_name, result) -> None
        on_failure: Hook called on failure (ctx, step_name, error) -> None
        pivot: If True, marks this step as a point of no return (v1.3.0).
               Once completed, ancestor steps become tainted and cannot be
               rolled back. Use for irreversible actions like payment charges.

    Example:
        >>> class OrderSaga(Saga):
        ...     @step(name="reserve_inventory")
        ...     async def reserve(self, ctx):
        ...         return {"reservation_id": "RES-123"}
        ...
        ...     @step(name="charge_payment", depends_on=["reserve_inventory"], pivot=True)
        ...     async def charge(self, ctx):
        ...         # PIVOT: Once this completes, reserve_inventory cannot be rolled back
        ...         return {"charge_id": "CHG-456"}
    """

    def decorator(func: F) -> F:
        # Store metadata on the function
        func._saga_step_meta = StepMetadata(  # type: ignore[attr-defined]
            name=name,
            depends_on=depends_on or [],
            aggregate_type=aggregate_type,
            event_type=event_type,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            description=description or f"Execute {name}",
            on_enter=on_enter,
            on_success=on_success,
            on_failure=on_failure,
            pivot=pivot,
        )
        return func

    return decorator


def compensate(
    for_step: str,
    compensation_type: CompensationType = CompensationType.MECHANICAL,
    timeout_seconds: float = 30.0,
    max_retries: int = 3,
    description: str | None = None,
    on_compensate: OnCompensateHook | None = None,
) -> Callable[[F], F]:
    """
    Decorator to mark a method as compensation for a step.

    Compensation functions are called when a saga fails and needs to
    undo previously completed steps.

    Compensation dependencies are automatically derived from the forward
    action dependencies and reversed by the compensation graph.

    Compensation functions can optionally return values and access results
    from previously executed compensations when using the new
    `execute_compensations()` API.

    Args:
        for_step: Name of the step this compensates
        compensation_type: Type of compensation (MECHANICAL, SEMANTIC, MANUAL)
        timeout_seconds: Compensation timeout (default: 30s)
        max_retries: Maximum retry attempts (default: 3)
        description: Human-readable description
        on_compensate: Hook called when compensation runs (ctx, step_name) -> None

    Example:
        >>> @compensate("charge_payment", on_compensate=publish_refund_event)
        ... async def refund(self, ctx):
        ...     await PaymentService.refund(ctx["charge_id"])

    Example (New with result passing):
        >>> @compensate("cancel_order")
        ... async def cancel_order(self, ctx, comp_results=None):
        ...     cancellation = await OrderService.cancel(ctx["order_id"])
        ...     return {"cancellation_id": cancellation.id}
        ...
        >>> @compensate("charge_payment")
        ... async def refund(self, ctx, comp_results=None):
        ...     cancel_id = comp_results.get("cancel_order", {}).get("cancellation_id")
        ...     await PaymentService.refund(ctx["charge_id"], ref=cancel_id)
    """

    def decorator(func: F) -> F:
        func._saga_compensation_meta = CompensationMetadata(  # type: ignore[attr-defined]
            for_step=for_step,
            depends_on=[],  # No longer used - dependencies derived from forward actions
            compensation_type=compensation_type,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            description=description or f"Compensate {for_step}",
            on_compensate=on_compensate,
        )
        return func

    return decorator


# =============================================================================
# v1.3.0: Forward Recovery Decorator
# =============================================================================


@dataclass
class ForwardRecoveryMetadata:
    """
    Metadata attached to forward recovery handler functions via decorator.

    Forward recovery handlers are invoked when a step fails after a pivot
    has completed. Instead of rolling back, they decide how to proceed forward.
    """

    for_step: str
    """Name of the step this handles recovery for."""

    max_retries: int = 3
    """Maximum retry attempts if RETRY action returned."""

    timeout_seconds: float = 30.0
    """Handler timeout in seconds."""


def forward_recovery(
    for_step: str,
    max_retries: int = 3,
    timeout_seconds: float = 30.0,
) -> Callable[[F], F]:
    """
    Decorator to mark a method as forward recovery handler for a step.

    Forward recovery is invoked when a step fails AFTER a pivot has completed.
    Instead of traditional compensation (rollback), the handler decides how
    to proceed forward. This is essential for handling failures in committed
    zones where rollback is not possible.

    The handler must return a RecoveryAction enum value indicating what to do:
    - RETRY: Retry the failed step with the same parameters
    - RETRY_WITH_ALTERNATE: Retry with modified parameters
    - SKIP: Skip this step and continue forward
    - MANUAL_INTERVENTION: Escalate to human/manual handling
    - COMPENSATE_PIVOT: Trigger semantic compensation of pivot (rare)

    Args:
        for_step: Name of the step this handles recovery for
        max_retries: Maximum retry attempts if RETRY action returned (default: 3)
        timeout_seconds: Handler timeout (default: 30s)

    Example:
        >>> from sagaz import Saga, action, compensate, forward_recovery
        >>> from sagaz.execution.pivot import RecoveryAction
        >>>
        >>> class PaymentSaga(Saga):
        ...     saga_name = "payment"
        ...
        ...     @action("charge_payment", pivot=True)
        ...     async def charge(self, ctx):
        ...         return {"charge_id": "CHG-123"}
        ...
        ...     @action("ship_order", depends_on=["charge_payment"])
        ...     async def ship(self, ctx):
        ...         # May fail due to carrier issues
        ...         return {"shipment_id": "SHP-456"}
        ...
        ...     @forward_recovery("ship_order")
        ...     async def handle_shipping_failure(self, ctx, error) -> RecoveryAction:
        ...         '''Handle shipping failure after payment was charged.'''
        ...         retry_count = ctx.get("_ship_order_retries", 0)
        ...
        ...         if retry_count < 3:
        ...             ctx["_ship_order_retries"] = retry_count + 1
        ...             return RecoveryAction.RETRY
        ...
        ...         if await self.has_alternate_carrier():
        ...             ctx["use_alternate_carrier"] = True
        ...             return RecoveryAction.RETRY_WITH_ALTERNATE
        ...
        ...         return RecoveryAction.MANUAL_INTERVENTION

    See Also:
        - RecoveryAction: Enum of possible actions to return
        - ADR-023: Pivot/Irreversible Steps documentation
    """

    def decorator(func: F) -> F:
        func._saga_forward_recovery_meta = ForwardRecoveryMetadata(  # type: ignore[attr-defined]
            for_step=for_step,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
        return func

    return decorator


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


class Saga:
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
        self._collect_steps()

        # If decorated methods were found, we're in declarative mode
        if self._steps:
            self._mode = "declarative"
            # saga_name takes precedence, then name parameter
            if self.saga_name is None and name is not None:  # pragma: no cover
                self.saga_name = name  # pragma: no cover
        else:
            # No decorators found - allow imperative mode
            # Name is required for imperative usage
            if name is not None:
                self.saga_name = name

    def _collect_steps(self) -> None:
        """Collect decorated methods into step definitions."""
        self._collect_step_methods()
        self._attach_compensations()
        self._collect_forward_recovery_handlers()

    def _collect_step_methods(self) -> None:
        """First pass: collect all step methods."""
        for attr_name in dir(self):
            if attr_name.startswith("_"):
                continue
            attr = getattr(self, attr_name)
            if hasattr(attr, "_saga_step_meta"):
                self._register_step_from_decorator(attr)

    def _register_step_from_decorator(self, method) -> None:
        """Register a step from a decorated method."""
        meta: StepMetadata = method._saga_step_meta
        step_def = SagaStepDefinition(
            step_id=meta.name,
            forward_fn=method,
            depends_on=meta.depends_on.copy(),
            aggregate_type=meta.aggregate_type,
            event_type=meta.event_type,
            timeout_seconds=meta.timeout_seconds,
            max_retries=meta.max_retries,
            description=meta.description,
            on_enter=meta.on_enter,
            on_success=meta.on_success,
            on_failure=meta.on_failure,
            pivot=meta.pivot,
        )
        self._steps.append(step_def)
        self._step_registry[meta.name] = step_def

    def _attach_compensations(self) -> None:
        """Second pass: attach compensations to steps."""
        for attr_name in dir(self):
            if attr_name.startswith("_"):
                continue
            attr = getattr(self, attr_name)
            if hasattr(attr, "_saga_compensation_meta"):
                self._attach_compensation_to_step(attr)

    def _attach_compensation_to_step(self, method) -> None:
        """Attach a compensation method to its corresponding step."""
        meta: CompensationMetadata = method._saga_compensation_meta
        step_name = meta.for_step
        if step_name not in self._step_registry:
            return  # pragma: no cover - compensate for unknown step
        step = self._step_registry[step_name]
        step.compensation_fn = method
        # Compensation dependencies are derived from forward dependencies (step.depends_on)
        # No need to set step.compensation_depends_on - it's ignored
        step.compensation_type = meta.compensation_type
        step.compensation_timeout_seconds = meta.timeout_seconds
        step.on_compensate = meta.on_compensate

    def _collect_forward_recovery_handlers(self) -> None:
        """Third pass: collect forward recovery handlers."""
        for attr_name in dir(self):
            if attr_name.startswith("_"):
                continue
            attr = getattr(self, attr_name)
            if hasattr(attr, "_saga_forward_recovery_meta"):
                meta: ForwardRecoveryMetadata = attr._saga_forward_recovery_meta
                self._forward_recovery_handlers[meta.for_step] = attr
                logger.debug(f"Registered forward recovery handler for step: {meta.for_step}")

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

        return newly_tainted

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
                "Choose one approach: either use decorators (declarative) or add_step() (imperative), "
                "but not both. See Saga class docstring for examples."
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

    def to_mermaid(
        self,
        direction: str = "TB",
        show_compensation: bool = True,
        highlight_trail: dict[str, Any] | None = None,
        show_state_markers: bool = True,
    ) -> str:
        """
        Generate a Mermaid flowchart diagram of the saga.

        Shows a decision tree where each step can succeed (go to next) or fail
        (trigger compensation chain backwards).

        Colors:
        - Success path: green arrows and styling
        - Failure/compensation path: amber/yellow styling
        - Highlighted trail: bold styling for executed steps

        Args:
            direction: Flowchart direction - "TB" (top-bottom), "LR" (left-right)
            show_compensation: If True, show compensation nodes and fail branches
            highlight_trail: Optional dict with execution trail info:
                - completed_steps: list of step names that completed successfully
                - failed_step: name of step that failed (if any)
                - compensated_steps: list of steps that were compensated
            show_state_markers: If True, show initial (●) and final (◎) state nodes

        Returns:
            Mermaid diagram string that can be rendered in markdown.

        Example:
            >>> saga.to_mermaid(highlight_trail={
            ...     "completed_steps": ["reserve", "charge"],
            ...     "failed_step": "ship",
            ...     "compensated_steps": ["charge", "reserve"]
            ... })
        """
        from sagaz.visualization.mermaid import HighlightTrail, MermaidGenerator, StepInfo

        # Convert steps to StepInfo format
        steps = [
            StepInfo(
                name=s.step_id,
                has_compensation=s.compensation_fn is not None,
                depends_on=set(s.depends_on),
            )
            for s in self._steps
        ]

        # Create generator and generate diagram
        generator = MermaidGenerator(
            steps=steps,
            direction=direction,
            show_compensation=show_compensation,
            show_state_markers=show_state_markers,
            highlight_trail=HighlightTrail.from_dict(highlight_trail),
        )

        return generator.generate()

    async def to_mermaid_with_execution(
        self,
        saga_id: str,
        storage: "SagaStorage",
        direction: str = "TB",
        show_compensation: bool = True,
        show_state_markers: bool = True,
    ) -> str:
        """
        Generate Mermaid diagram with execution trail from storage.

        Fetches the saga execution state from storage and highlights
        the actual path taken.

        Args:
            saga_id: The saga execution ID to visualize
            storage: SagaStorage instance to fetch execution data from
            direction: Flowchart direction
            show_compensation: If True, show compensation nodes
            show_state_markers: If True, show initial/final nodes

        Returns:
            Mermaid diagram with highlighted execution trail.

        Example:
            >>> from sagaz.storage import PostgreSQLSagaStorage
            >>> storage = PostgreSQLSagaStorage(...)
            >>> diagram = await saga.to_mermaid_with_execution(
            ...     saga_id="abc-123",
            ...     storage=storage
            ... )
        """
        # Fetch saga state from storage
        saga_data = await storage.load_saga_state(saga_id)

        if not saga_data:  # pragma: no cover
            # No execution found, return diagram without highlighting
            return self.to_mermaid(
                direction, show_compensation, None, show_state_markers
            )  # pragma: no cover

        # Parse steps to build highlight trail
        steps_data = saga_data.get("steps", [])
        completed_steps = set()
        failed_step = None
        compensated_steps = set()

        for step in steps_data:
            status = step.get("status")
            name = step.get("name")

            if status == "completed":
                completed_steps.add(name)
            elif status == "failed":  # pragma: no cover
                failed_step = name  # pragma: no cover
            elif status == "compensated":  # pragma: no cover
                compensated_steps.add(name)  # pragma: no cover
                # A compensated step must have completed first
                completed_steps.add(name)  # pragma: no cover
            elif status == "compensating":  # pragma: no cover
                compensated_steps.add(name)  # pragma: no cover
                completed_steps.add(name)  # pragma: no cover

        # Build highlight trail
        highlight_trail = {
            "completed_steps": list(completed_steps),
            "failed_step": failed_step,
            "compensated_steps": list(compensated_steps),
        }

        return self.to_mermaid(direction, show_compensation, highlight_trail, show_state_markers)

    def to_mermaid_markdown(
        self,
        direction: str = "TB",
        show_compensation: bool = True,
        highlight_trail: dict[str, Any] | None = None,
        show_state_markers: bool = True,
    ) -> str:
        """
        Generate a Mermaid diagram wrapped in markdown code fence.

        Args:
            direction: Flowchart direction
            show_compensation: If True, show compensation nodes and flows
            highlight_trail: Optional execution trail to highlight
            show_state_markers: If True, show initial/final nodes

        Returns:
            Mermaid diagram in markdown format.
        """
        return f"```mermaid\n{self.to_mermaid(direction, show_compensation, highlight_trail, show_state_markers)}\n```"

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
        for step in current_level:
            remaining.remove(step.step_id)
            for other_id in remaining:
                if step.step_id in step_map[other_id].depends_on:
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
        self._initialize_run(initial_context, saga_id)
        name = self._get_saga_name()
        self._register_compensations()

        # Persist start
        storage = self._config.storage if self._config else None
        if storage:
            try:
                await storage.save_saga_state(
                    self._saga_id,
                    name,
                    SagaStatus.EXECUTING,
                    [],  # TODO: Track steps
                    self._context,
                )
            except Exception as e:  # pragma: no cover
                logger.warning(f"Failed to persist saga start: {e}")  # pragma: no cover

        try:
            await self._notify_listeners("on_saga_start", name, self._saga_id, self._context)
            await self._execute_all_levels()
            await self._notify_listeners("on_saga_complete", name, self._saga_id, self._context)

            # Persist completion
            if storage:
                try:
                    await storage.save_saga_state(
                        self._saga_id, name, SagaStatus.COMPLETED, [], self._context
                    )
                except Exception as e:  # pragma: no cover
                    logger.warning(f"Failed to persist saga completion: {e}")  # pragma: no cover

            return self._context
        except Exception as e:
            await self._compensate()
            await self._notify_listeners("on_saga_failed", name, self._saga_id, self._context, e)

            # Persist failure
            if storage:
                try:
                    await storage.save_saga_state(
                        self._saga_id, name, SagaStatus.ROLLED_BACK, [], self._context
                    )
                except Exception as e_storage:  # pragma: no cover
                    logger.warning(
                        f"Failed to persist saga failure: {e_storage}"
                    )  # pragma: no cover

            raise

    def _initialize_run(self, initial_context: dict[str, Any], saga_id: str | None) -> None:
        """Initialize saga run state."""
        import uuid

        self._saga_id = saga_id or initial_context.get("saga_id") or str(uuid.uuid4())
        self._context = initial_context.copy()
        self._context["saga_id"] = self._saga_id
        self._compensation_graph.reset_execution()

    def _register_compensations(self) -> None:
        """Register all compensations in the graph.

        Compensation dependencies are automatically derived from forward
        action dependencies. The compensation graph will auto-reverse them.
        """
        for step in self._steps:
            if step.compensation_fn:
                self._compensation_graph.register_compensation(
                    step.step_id,
                    step.compensation_fn,
                    depends_on=step.depends_on,  # Use forward dependencies (will be auto-reversed)
                    compensation_type=step.compensation_type,
                    max_retries=step.max_retries,
                    timeout_seconds=step.compensation_timeout_seconds,
                )

    async def _execute_all_levels(self) -> None:
        """Execute steps level by level."""
        for level in self.get_execution_order():
            await self._execute_level(level)

    def _get_saga_name(self) -> str:
        """Get the saga name from class attribute or class name."""
        return self.saga_name or self.__class__.__name__

    async def _notify_listeners(self, event_name: str, *args) -> None:
        """Notify all listeners of an event."""
        for listener in self._instance_listeners:
            try:
                handler = getattr(listener, event_name, None)
                if handler:
                    result = handler(*args)
                    if inspect.iscoroutine(result):
                        await result
            except Exception as e:
                logger.warning(f"Listener {type(listener).__name__}.{event_name} error: {e}")

    async def _execute_level(self, level: list[SagaStepDefinition]) -> None:
        """Execute all steps in a level concurrently."""
        if not level:
            return  # pragma: no cover

        tasks = [self._execute_step(step) for step in level]

        # Execute in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check for exceptions
        for result in results:
            if isinstance(result, Exception):
                raise result

    async def _execute_step(self, step: SagaStepDefinition) -> None:
        """Execute a single step with lifecycle hooks and listeners."""
        saga_name = self._get_saga_name()

        # Notify listeners: step entering
        await self._notify_listeners("on_step_enter", saga_name, step.step_id, self._context)

        # Call on_enter hook
        await self._call_hook(step.on_enter, self._context, step.step_id)

        try:
            # Apply timeout
            result = await asyncio.wait_for(
                step.forward_fn(self._context), timeout=step.timeout_seconds
            )

            # Merge result into context
            if result and isinstance(result, dict):
                self._context.update(result)

            # Mark step as executed for compensation tracking
            self._context[f"__{step.step_id}_completed"] = True
            self._compensation_graph.mark_step_executed(step.step_id)

            # Handle pivot step completion - propagate taint to ancestors
            if step.pivot:
                self._propagate_taint_from_pivot(step.step_id)
                logger.info(f"Pivot step '{step.step_id}' completed - ancestors are now tainted")

            # Call on_success hook
            await self._call_hook(step.on_success, self._context, step.step_id, result)

            # Notify listeners: step success
            await self._notify_listeners(
                "on_step_success", saga_name, step.step_id, self._context, result
            )

        except TimeoutError as e:
            # Call on_failure hook
            await self._call_hook(step.on_failure, self._context, step.step_id, e)
            # Notify listeners: step failure
            await self._notify_listeners(
                "on_step_failure", saga_name, step.step_id, self._context, e
            )
            msg = f"Step '{step.step_id}' timed out after {step.timeout_seconds}s"
            raise TimeoutError(msg)
        except Exception as e:
            # Call on_failure hook
            await self._call_hook(step.on_failure, self._context, step.step_id, e)
            # Notify listeners: step failure
            await self._notify_listeners(
                "on_step_failure", saga_name, step.step_id, self._context, e
            )
            raise

    async def _call_hook(self, hook: Callable | None, *args) -> None:
        """Call a hook function, handling both sync and async hooks."""
        if hook is None:
            return

        try:
            result = hook(*args)
            # If it's a coroutine, await it
            if inspect.iscoroutine(result):
                await result
        except Exception as e:
            # Log but don't fail - hooks should not break saga execution
            logger.warning(f"Hook error (non-fatal): {e}")

    async def _compensate(self) -> None:
        """
        Execute compensations in dependency order, respecting pivot boundaries.

        v1.3.0: Compensation stops at pivot boundaries. Tainted steps (ancestors
        of completed pivots) are skipped, as are pivot steps themselves.
        """
        comp_levels = self._compensation_graph.get_compensation_order()

        # Track how many steps we skip due to taint
        skipped_count = 0

        for level in comp_levels:
            # v1.3.0: Filter out tainted steps and pivot steps
            compensable_steps = []
            for step_id in level:
                if self._is_step_tainted(step_id):
                    logger.info(f"Skipping compensation for tainted step: {step_id}")
                    skipped_count += 1
                    continue

                step = self._step_registry.get(step_id)
                if step and step.pivot and step_id in self._completed_pivots:
                    logger.info(f"Reached pivot boundary, stopping compensation: {step_id}")
                    skipped_count += 1
                    continue

                compensable_steps.append(step_id)

            if compensable_steps:
                tasks = [self._execute_compensation(step_id) for step_id in compensable_steps]
                # Execute compensations in parallel, don't fail on individual errors
                await asyncio.gather(*tasks, return_exceptions=True)

        if skipped_count > 0:
            logger.info(f"Pivot-aware compensation: skipped {skipped_count} tainted/pivot steps")

    async def _execute_compensation(self, step_id: str) -> None:
        """Execute a single compensation with lifecycle hook and listeners."""
        node = self._compensation_graph.get_compensation_info(step_id)
        if not node:
            return  # pragma: no cover

        # v1.3.0: Double-check taint status (in case it changed)
        if self._is_step_tainted(step_id):  # pragma: no cover
            logger.debug(f"Skipping compensation for tainted step: {step_id}")
            return

        saga_name = self._get_saga_name()

        # Get the on_compensate hook from the step definition
        step = self._step_registry.get(step_id)
        on_compensate = step.on_compensate if step else None

        try:
            # Notify listeners: compensation starting
            await self._notify_listeners("on_compensation_start", saga_name, step_id, self._context)

            # Call on_compensate hook before compensation
            await self._call_hook(on_compensate, self._context, step_id)

            await asyncio.wait_for(
                node.compensation_fn(self._context), timeout=node.timeout_seconds
            )
            self._context[f"__{step_id}_compensated"] = True

            # Notify listeners: compensation complete
            await self._notify_listeners(
                "on_compensation_complete", saga_name, step_id, self._context
            )
        except Exception as e:
            # Log but don't fail - we want all compensations to attempt
            self._context[f"__{step_id}_compensation_error"] = str(e)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(steps={len(self._steps)})"


# @action is the primary decorator name for defining saga step actions
# @step is an internal alias kept for now but @action is preferred
action = step
