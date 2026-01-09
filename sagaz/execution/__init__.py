# ============================================
# FILE: sagaz/execution/__init__.py
# ============================================
"""
Execution module for Sagaz - contains execution graph and orchestration logic.

This module re-exports all execution components for backward compatibility.
"""

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
from sagaz.execution.orchestrator import SagaOrchestrator
from sagaz.execution.pivot import (
    PivotInfo,
    RecoveryAction,
    SagaZones,
    StepZone,
    TaintPropagator,
)
from sagaz.execution.state_machine import SagaStateMachine

__all__ = [
    # Graph
    "CircularDependencyError",
    "CompensationFailureStrategy",
    "CompensationGraphError",
    "CompensationNode",
    "CompensationResult",
    "CompensationType",
    # Pivot
    "PivotInfo",
    "RecoveryAction",
    "SagaCompensationContext",
    "SagaExecutionGraph",
    # Orchestrator
    "SagaOrchestrator",
    # State Machine
    "SagaStateMachine",
    "SagaZones",
    "StepZone",
    "TaintPropagator",
]
