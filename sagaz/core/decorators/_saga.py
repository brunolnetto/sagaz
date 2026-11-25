"""Declarative ``Saga`` base class and ``SagaStepDefinition``."""

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sagaz.core.decorators._collection import DecoratorCollectionManager
from sagaz.core.decorators._execution import ExecutionEngine
from sagaz.core.decorators._ordering import _DecoratorOrderingMixin
from sagaz.core.decorators._pivot import _DecoratorPivotMixin
from sagaz.core.decorators._step_chart import _DecoratorStepChartMixin
from sagaz.core.decorators._steps import (
    OnCompensateHook,
    OnEnterHook,
    OnExitHook,
    OnFailureHook,
    OnSuccessHook,
    StepKey,
)
from sagaz.core.decorators._visualization import _DecoratorVisualizationMixin
from sagaz.core.execution.graph import CompensationType, SagaExecutionGraph
from sagaz.core.logger import get_logger
from sagaz.core.tenant import (
    TenantContext,
    ensure_tenant_context_matches,
    resolve_tenant,
    tenant_argument,
    tenant_execution,
)

if TYPE_CHECKING:
    from sagaz.core.config import SagaConfig

logger = get_logger("sagaz.core.decorators")


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
    timeout_seconds: float | None = None
    """None: ``SagaConfig.default_timeout`` (60 s unless configured)."""
    compensation_timeout_seconds: float = 30.0
    compensation_max_retries: int = 3
    """Retries of a failing compensation (``@compensate(max_retries=)``), with backoff."""
    max_retries: int | None = None
    """None: ``SagaConfig.default_max_retries`` (3 unless configured)."""
    description: str | None = None
    # Lifecycle hooks
    on_enter: OnEnterHook | None = None
    on_success: OnSuccessHook | None = None
    on_failure: OnFailureHook | None = None
    on_exit: OnExitHook | None = None
    on_compensate: OnCompensateHook | None = None
    # v1.3.0: Pivot support
    pivot: bool = False
    """If True, marks this step as a point of no return (irreversible)."""
    # v2.0.0: Region affinity (ADR-034)
    region: str | None = None
    """Region whose workers run this step and its compensation; None = local."""
    idempotency_key: StepKey | None = None
    """What makes the step's effect unique per tenant, across sagas (#569)."""


class Saga(
    _DecoratorPivotMixin,
    _DecoratorOrderingMixin,
    _DecoratorVisualizationMixin,
    _DecoratorStepChartMixin,
):
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
    retry_backoff_base: float = 0.01
    """Seconds before a step's first retry; doubles on each further retry."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Auto-register triggers
        # Import inside method to avoid circular imports
        from sagaz.core.triggers.registry import TriggerRegistry

        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if hasattr(method, "_trigger_metadata"):
                TriggerRegistry.register(cls, name, method._trigger_metadata)

    def __init__(
        self,
        name: str | None = None,
        config: "SagaConfig | None" = None,
        *,
        use_step_statechart: bool | None = None,
    ) -> None:
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
            use_step_statechart: Run on the step chart (StateChart phase 3, ADR-040).
                None (default): the class attribute, else ``config.use_step_statechart``.

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
        self._init_step_chart(use_step_statechart)

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

    # =========================================================================
    # Imperative API Support - add_step() for programmatic saga building
    # =========================================================================

    def add_step(
        self,
        name: str,
        action: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]],
        compensation: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        depends_on: list[str] | None = None,
        timeout_seconds: float | None = None,
        compensation_timeout_seconds: float = 30.0,
        max_retries: int | None = None,
        compensation_max_retries: int = 3,
        description: str | None = None,
        region: str | None = None,
        idempotency_key: StepKey | None = None,
    ) -> "Saga":
        """
        Add a step programmatically (imperative mode).

        Args:
            name: Unique step identifier
            action: Async function that takes context dict and returns updated context
            compensation: Async function to undo this step on failure
            depends_on: List of step names that must complete before this step
            timeout_seconds: Timeout of each attempt (default: ``SagaConfig.default_timeout``,
                60 s unless configured)
            compensation_timeout_seconds: Compensation timeout (default: 30s)
            max_retries: Retries after the first attempt fails (default:
                ``SagaConfig.default_max_retries``, 3 unless configured)
            description: Human-readable description
            region: Run the step and its compensation on this region's workers
                (ADR-034). ``None`` (default) runs it locally.
            idempotency_key: As for ``@action``: the step runs once per key (#569).

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
            compensation_max_retries=compensation_max_retries,
            max_retries=max_retries,
            description=description or f"Execute {name}",
            region=region,
            idempotency_key=idempotency_key,
        )

        self._steps.append(step_def)
        self._step_registry[name] = step_def

        return self  # Enable method chaining

    def add_listener(self, listener: Any) -> "Saga":
        """Add a listener to this saga's, keeping the configured ones (#538).

        The class attribute ``listeners`` replaces the config's logging, metrics and
        tracing listeners; this adds one to them (as ``SagaConfig.extra_listeners``
        does for every saga).
        """
        self._instance_listeners = [*self._instance_listeners, listener]
        return self

    def get_steps(self) -> list[SagaStepDefinition]:
        """Get all step definitions."""
        return self._steps.copy()

    def get_step(self, name: str) -> SagaStepDefinition | None:
        """Get a specific step by name."""
        return self._step_registry.get(name)

    async def run(
        self,
        initial_context: dict[str, Any],
        saga_id: str | None = None,
        *,
        tenant: TenantContext | str | None = None,
        allow_rerun: bool = False,
        tenant_context: TenantContext | str | None = None,
    ) -> dict[str, Any]:
        """
        Execute this saga.

        Args:
            initial_context: Initial data for the saga
            saga_id: Identifies the run; a new id is generated when omitted. A saga
                id runs once: one that already exists in storage raises
                ``SagaAlreadyExistsError`` before any step runs, so a retried
                request does not run its steps (charge, ship) twice.
            tenant: Run as this tenant (ADR-020): a ``TenantContext`` or a tenant
                id. Storage is scoped to it, its quotas apply, and
                ``ctx["tenant_id"]`` is set. A tenant id is resolved through
                ``SagaConfig.tenant_registry`` when one is configured.
            allow_rerun: Run an existing ``saga_id`` again, all its steps included
                (an event-sourced stream or unified-log transaction continues).
            tenant_context: Deprecated name of ``tenant`` (until 3.0).

        Returns:
            Final context with all step results merged

        Raises:
            SagaAlreadyExistsError: ``saga_id`` already exists and ``allow_rerun`` is False.
            SagaPersistenceError: the state could not be saved (see
                ``SagaConfig.tolerate_persistence_errors``).
            Exception: If saga fails (compensations will be attempted first)
        """
        if not isinstance(initial_context, Mapping):
            msg = (
                f"initial_context must be a dict (a mapping of names to values), "
                f"got {type(initial_context).__name__}"
            )
            raise TypeError(msg)
        initial_context = dict(initial_context)
        given = tenant_argument("Saga.run", tenant, tenant_context=tenant_context)
        if given is None:
            return await self._engine(allow_rerun).run(initial_context, saga_id)
        registry = getattr(self._config, "tenant_registry", None)
        resolved = resolve_tenant(given, registry)
        ensure_tenant_context_matches(initial_context, resolved.tenant_id)
        async with tenant_execution(resolved):
            context = {**initial_context, "tenant_id": resolved.tenant_id}
            return await self._engine(allow_rerun).run(context, saga_id)

    def _engine(self, allow_rerun: bool) -> ExecutionEngine:
        engine = ExecutionEngine(self)
        engine.allow_rerun = allow_rerun
        return engine

    # Backward compatibility methods (private methods moved to ExecutionEngine)
    def _initialize_run(self, initial_context: dict[str, Any], saga_id: str | None) -> None:
        """Backward compatible: Initialize saga run state."""
        engine = ExecutionEngine(self)
        engine._initialize_run(initial_context, saga_id)

    def _register_compensations(self) -> None:
        """Backward compatible: Register all compensations in the graph."""
        engine = ExecutionEngine(self)
        engine._register_compensations()

    async def _execute_level(self, level_steps: list) -> None:
        """Backward compatible: Execute all steps in a level."""
        engine = ExecutionEngine(self)
        await engine._execute_level(level_steps)

    async def _execute_compensation(self, step_id: str) -> None:
        """Backward compatible: Execute compensation for a specific step."""
        engine = ExecutionEngine(self)
        await engine._execute_compensation(step_id)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(steps={len(self._steps)})"
