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
    ...     @compensate("charge_payment", depends_on=["create_order"])
    ...     async def refund(self, ctx):
    ...         await PaymentService.refund(ctx["charge_id"])
"""

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from sagaz.storage.base import SagaStorage

from sagaz.compensation_graph import CompensationType, SagaCompensationGraph

logger = logging.getLogger(__name__)

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

    Example:
        >>> class OrderSaga(Saga):
        ...     @step(name="create_order", on_success=publish_order_created)
        ...     async def create_order(self, ctx):
        ...         order = await OrderService.create(ctx["order_data"])
        ...         return {"order_id": order.id}
    """

    def decorator(func: F) -> F:
        # Store metadata on the function
        func._saga_step_meta = StepMetadata(
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
        )
        return func

    return decorator


def compensate(
    for_step: str,
    depends_on: list[str] | None = None,
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

    Args:
        for_step: Name of the step this compensates
        depends_on: Steps whose compensations must complete BEFORE this one
        compensation_type: Type of compensation (MECHANICAL, SEMANTIC, MANUAL)
        timeout_seconds: Compensation timeout (default: 30s)
        max_retries: Maximum retry attempts (default: 3)
        description: Human-readable description
        on_compensate: Hook called when compensation runs (ctx, step_name) -> None

    Example:
        >>> @compensate("charge_payment", on_compensate=publish_refund_event)
        ... async def refund(self, ctx):
        ...     await PaymentService.refund(ctx["charge_id"])
    """

    def decorator(func: F) -> F:
        func._saga_compensation_meta = CompensationMetadata(
            for_step=for_step,
            depends_on=depends_on or [],
            compensation_type=compensation_type,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            description=description or f"Compensate {for_step}",
            on_compensate=on_compensate,
        )
        return func

    return decorator


@dataclass
class SagaStepDefinition:
    """
    Complete definition of a saga step with its compensation.

    Used internally to track step and compensation pairs.
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
        >>> from sagaz.listeners import LoggingSagaListener, MetricsSagaListener
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

    def __init__(self, config=None):
        """
        Initialize the saga.

        Args:
            config: Optional SagaConfig. If not provided, uses global config.
        """
        self._steps: list[SagaStepDefinition] = []
        self._step_registry: dict[str, SagaStepDefinition] = {}
        self._compensation_graph = SagaCompensationGraph()
        self._context: dict[str, Any] = {}
        self._saga_id: str = ""

        # Use provided config or global config
        if config is not None:
            self._config = config
        else:
            from sagaz.config import get_config

            self._config = get_config()

        # If no class-level listeners defined, use config listeners
        if self.listeners is None and self._config:
            self._instance_listeners = self._config.listeners
        else:
            self._instance_listeners = self.listeners or []

        self._collect_steps()

    def _collect_steps(self) -> None:
        """Collect decorated methods into step definitions."""
        self._collect_step_methods()
        self._attach_compensations()

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
            return
        step = self._step_registry[step_name]
        step.compensation_fn = method
        step.compensation_depends_on = meta.depends_on.copy()
        step.compensation_type = meta.compensation_type
        step.compensation_timeout_seconds = meta.timeout_seconds
        step.on_compensate = meta.on_compensate

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
        highlight_trail: dict[str, any] | None = None,
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
        lines = [f"flowchart {direction}"]

        # Collect steps with compensation and determine execution order
        compensable_steps = [s for s in self._steps if s.compensation_fn is not None]
        has_any_deps = any(step.depends_on for step in self._steps)

        # Build step order
        if has_any_deps:
            execution_levels = self.get_execution_order()
            ordered_steps = [step for level in execution_levels for step in level]
        else:
            ordered_steps = self._steps.copy()

        # Parse highlight trail
        completed = set(highlight_trail.get("completed_steps", [])) if highlight_trail else set()
        failed_step = highlight_trail.get("failed_step") if highlight_trail else None
        compensated = (
            set(highlight_trail.get("compensated_steps", [])) if highlight_trail else set()
        )

        # Find root and leaf steps
        all_deps: set[str] = set()
        for step in self._steps:
            all_deps.update(step.depends_on)
        root_steps = [s for s in ordered_steps if not s.depends_on]
        leaf_steps = [s for s in ordered_steps if s.step_id not in all_deps]

        # Add initial state marker
        if show_state_markers:
            lines.append("    START((●))")

        # Add step nodes (happy path)
        for step in ordered_steps:
            has_comp = step.compensation_fn is not None
            is_root = not step.depends_on

            # Determine node shape
            if is_root:
                shape = f"([{step.step_id}])"
            elif has_comp:
                shape = f"[{step.step_id}]"
            else:
                shape = f"[/{step.step_id}/]"

            lines.append(f"    {step.step_id}{shape}")

        # Add final state markers
        if show_state_markers:
            lines.append("    SUCCESS((◎))")
            if show_compensation and compensable_steps:
                lines.append("    ROLLED_BACK((◎))")

        # Add compensation nodes if enabled
        if show_compensation:
            for step in compensable_steps:
                lines.append(f"    comp_{step.step_id}{{{{undo {step.step_id}}}}}")

        # Connect START to root steps
        if show_state_markers:
            for step in root_steps:
                lines.append(f"    START --> {step.step_id}")

        # Add success edges (happy path) - GREEN
        for step in ordered_steps:
            for dep in sorted(step.depends_on):
                lines.append(f"    {dep} --> {step.step_id}")

        # For sequential sagas, show chain
        if not has_any_deps and len(ordered_steps) > 1:
            for i in range(len(ordered_steps) - 1):
                lines.append(f"    {ordered_steps[i].step_id} --> {ordered_steps[i + 1].step_id}")

        # Connect leaf steps to SUCCESS
        if show_state_markers:
            for step in leaf_steps:
                lines.append(f"    {step.step_id} --> SUCCESS")

        # Add failure + compensation edges if enabled - RED
        if show_compensation and compensable_steps:
            # Each step with compensation has a fail edge to its compensation
            for step in compensable_steps:
                lines.append(f"    {step.step_id} -. fail .-> comp_{step.step_id}")

            # Compensation chain
            if has_any_deps:
                for step in compensable_steps:
                    for dep in sorted(step.depends_on):
                        dep_step = self._step_registry.get(dep)
                        if dep_step and dep_step.compensation_fn is not None:
                            lines.append(f"    comp_{step.step_id} -.-> comp_{dep}")
            else:
                comp_order = [s.step_id for s in ordered_steps if s.compensation_fn is not None]
                for i in range(len(comp_order) - 1, 0, -1):
                    lines.append(f"    comp_{comp_order[i]} -.-> comp_{comp_order[i - 1]}")

            # Connect root compensations to ROLLED_BACK
            if show_state_markers:
                root_comp_steps = [s for s in compensable_steps if not s.depends_on]
                for step in root_comp_steps:
                    lines.append(f"    comp_{step.step_id} -.-> ROLLED_BACK")

        # Add styling
        lines.append("")
        lines.append("    %% Styling")
        lines.append("    classDef success fill:#d4edda,stroke:#28a745,color:#155724")
        lines.append("    classDef failure fill:#f8d7da,stroke:#dc3545,color:#721c24")
        lines.append("    classDef compensation fill:#fff3cd,stroke:#ffc107,color:#856404")
        lines.append("    classDef highlighted stroke-width:3px")
        lines.append("    classDef startEnd fill:#333,stroke:#333,color:#fff")
        lines.append("    classDef dimmed fill:#e9ecef,stroke:#adb5bd,color:#6c757d")

        step_names = [s.step_id for s in ordered_steps]
        comp_names = [f"comp_{s.step_id}" for s in compensable_steps] if show_compensation else []

        # When trail is provided, only executed nodes get colored
        if highlight_trail:
            # First dim all nodes
            if step_names:
                lines.append(f"    class {','.join(step_names)} dimmed")
            if comp_names:
                lines.append(f"    class {','.join(comp_names)} dimmed")

            # Then color executed nodes
            if completed:
                lines.append(f"    class {','.join(sorted(completed))} success")
                lines.append(f"    class {','.join(sorted(completed))} highlighted")

            if failed_step:
                lines.append(f"    class {failed_step} failure")
                lines.append(f"    class {failed_step} highlighted")

            if compensated:
                comp_highlighted = [f"comp_{s}" for s in sorted(compensated)]
                lines.append(f"    class {','.join(comp_highlighted)} compensation")
                lines.append(f"    class {','.join(comp_highlighted)} highlighted")
        else:
            # Default: all steps success, all comps compensation
            if step_names:
                lines.append(f"    class {','.join(step_names)} success")
            if comp_names:
                lines.append(f"    class {','.join(comp_names)} compensation")

        # Style state markers
        if show_state_markers:
            state_markers = ["START", "SUCCESS"]
            if show_compensation and compensable_steps:
                state_markers.append("ROLLED_BACK")
            lines.append(f"    class {','.join(state_markers)} startEnd")

        # Style the links
        lines.append("")
        lines.append("    linkStyle default stroke:#28a745")

        return "\n".join(lines)

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
        saga_state = await storage.get_saga_state(saga_id)

        if not saga_state:
            # No execution found, return diagram without highlighting
            return self.to_mermaid(direction, show_compensation, None, show_state_markers)

        # Build highlight trail from saga state
        highlight_trail = {
            "completed_steps": list(saga_state.completed_steps),
            "failed_step": saga_state.failed_step,
            "compensated_steps": list(saga_state.compensated_steps),
        }

        return self.to_mermaid(direction, show_compensation, highlight_trail, show_state_markers)

    def to_mermaid_markdown(
        self,
        direction: str = "TB",
        show_compensation: bool = True,
        highlight_trail: dict[str, any] | None = None,
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

        try:
            await self._notify_listeners("on_saga_start", name, self._saga_id, self._context)
            await self._execute_all_levels()
            await self._notify_listeners("on_saga_complete", name, self._saga_id, self._context)
            return self._context
        except Exception as e:
            await self._compensate()
            await self._notify_listeners("on_saga_failed", name, self._saga_id, self._context, e)
            raise

    def _initialize_run(self, initial_context: dict[str, Any], saga_id: str | None) -> None:
        """Initialize saga run state."""
        import uuid

        self._saga_id = saga_id or initial_context.get("saga_id") or str(uuid.uuid4())
        self._context = initial_context.copy()
        self._context["saga_id"] = self._saga_id
        self._compensation_graph.reset_execution()

    def _register_compensations(self) -> None:
        """Register all compensations in the graph."""
        for step in self._steps:
            if step.compensation_fn:
                self._compensation_graph.register_compensation(
                    step.step_id,
                    step.compensation_fn,
                    depends_on=step.compensation_depends_on,
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
            return

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
        """Execute compensations in dependency order."""
        comp_levels = self._compensation_graph.get_compensation_order()

        for level in comp_levels:
            tasks = [self._execute_compensation(step_id) for step_id in level]
            # Execute compensations in parallel, don't fail on individual errors
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_compensation(self, step_id: str) -> None:
        """Execute a single compensation with lifecycle hook and listeners."""
        node = self._compensation_graph.get_compensation_info(step_id)
        if not node:
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


# Backward compatibility alias
DeclarativeSaga = Saga

# Terminology alias: @action is preferred over @step for clarity
# (A "step" conceptually contains both action AND compensation)
action = step
