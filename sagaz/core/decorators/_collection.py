"""Decorator collection and registration for saga steps.

Handles discovery and registration of @step, @compensate, and @forward_recovery
decorated methods from a saga class.
"""

from typing import TYPE_CHECKING

from sagaz.core.decorators._steps import (
    CompensationMetadata,
    ForwardRecoveryMetadata,
    StepMetadata,
)
from sagaz.core.logger import get_logger

if TYPE_CHECKING:
    from sagaz.core.decorators import Saga

logger = get_logger(__name__)


class DecoratorCollectionManager:
    """Manages collection of decorated methods from saga instances."""

    def __init__(self, saga: "Saga"):
        """Initialize manager with saga instance.

        Args:
            saga: The Saga instance to collect decorators from
        """
        self.saga = saga

    def collect_all(self) -> None:
        """Collect all decorated methods into saga step definitions.

        This is a three-pass process:
        1. Collect decorated step methods (@step, @action)
        2. Attach compensation methods (@compensate)
        3. Collect forward recovery handlers (@forward_recovery)
        """
        self._collect_step_methods()
        self._attach_compensations()
        self._collect_forward_recovery_handlers()

    def _collect_step_methods(self) -> None:
        """First pass: collect all step methods.

        Scans the saga instance for methods decorated with @step or @action.
        """
        for attr_name in dir(self.saga):
            if attr_name.startswith("_"):
                continue
            attr = getattr(self.saga, attr_name)
            if hasattr(attr, "_saga_step_meta"):
                self._register_step_from_decorator(attr)

    def _register_step_from_decorator(self, method) -> None:
        """Register a step from a decorated method.

        Args:
            method: A method decorated with @step or @action
        """
        from sagaz.core.decorators import SagaStepDefinition

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
        self.saga._steps.append(step_def)
        self.saga._step_registry[meta.name] = step_def

    def _attach_compensations(self) -> None:
        """Second pass: attach compensations to steps.

        Scans the saga instance for methods decorated with @compensate and
        attaches them to their corresponding steps.
        """
        for attr_name in dir(self.saga):
            if attr_name.startswith("_"):
                continue
            attr = getattr(self.saga, attr_name)
            if hasattr(attr, "_saga_compensation_meta"):
                self._attach_compensation_to_step(attr)

    def _attach_compensation_to_step(self, method) -> None:
        """Attach a compensation method to its corresponding step.

        Args:
            method: A method decorated with @compensate

        Compensation dependencies are automatically derived from forward action
        dependencies. The step's depends_on list is used.
        """
        meta: CompensationMetadata = method._saga_compensation_meta
        step_name = meta.for_step
        if step_name not in self.saga._step_registry:
            return  # compensate for unknown step
        step = self.saga._step_registry[step_name]
        step.compensation_fn = method
        # Compensation dependencies are derived from forward dependencies (step.depends_on)
        # No need to set step.compensation_depends_on - it's ignored
        step.compensation_type = meta.compensation_type
        step.compensation_timeout_seconds = meta.timeout_seconds
        step.on_compensate = meta.on_compensate

    def _collect_forward_recovery_handlers(self) -> None:
        """Third pass: collect forward recovery handlers.

        Scans the saga instance for methods decorated with @forward_recovery.
        """
        for attr_name in dir(self.saga):
            if attr_name.startswith("_"):
                continue
            attr = getattr(self.saga, attr_name)
            if hasattr(attr, "_saga_forward_recovery_meta"):
                meta: ForwardRecoveryMetadata = attr._saga_forward_recovery_meta
                self.saga._forward_recovery_handlers[meta.for_step] = attr
                logger.debug(f"Registered forward recovery handler for step: {meta.for_step}")
