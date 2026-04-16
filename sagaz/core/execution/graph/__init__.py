"""
Unified saga execution graph for forward execution and compensation.

Provides flexible dependency ordering for both action execution and compensation,
enabling parallel execution where safe. The same graph structure is used for both
directions by reversing dependencies for compensation.

Example:
    >>> graph = SagaExecutionGraph()
    >>> # Register steps with forward dependencies
    >>> graph.register_step("create_order", create_fn, cancel_fn)
    >>> graph.register_step("charge_payment", charge_fn, refund_fn, depends_on=["create_order"])
    >>>
    >>> # Get forward execution order
    >>> levels = graph.get_execution_order()
    >>>
    >>> # Get compensation order (automatically reversed)
    >>> comp_levels = graph.get_compensation_order()
"""

from sagaz.core.execution.graph._core import SagaExecutionGraph
from sagaz.core.execution.graph._exceptions import (
    CircularDependencyError,
    CompensationGraphError,
    MissingDependencyError,
)
from sagaz.core.execution.graph._tracker import _CompensationTracker
from sagaz.core.execution.graph._types import (
    CompensationFailureStrategy,
    CompensationNode,
    CompensationResult,
    CompensationType,
    SagaCompensationContext,
)
from sagaz.core.execution.graph._utils import _detect_compensation_signature

__all__ = [
    "CircularDependencyError",
    "CompensationFailureStrategy",
    "CompensationGraphError",
    "CompensationNode",
    "CompensationResult",
    "CompensationType",
    "MissingDependencyError",
    "SagaCompensationContext",
    "SagaExecutionGraph",
    "_CompensationTracker",
    "_detect_compensation_signature",
]
