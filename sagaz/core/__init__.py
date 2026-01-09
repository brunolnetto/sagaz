# ============================================
# FILE: sagaz/core/__init__.py
# ============================================
"""
Core module for Sagaz - contains the fundamental building blocks.

This module re-exports all core components for backward compatibility
with existing imports like `from sagaz.core.saga import Saga`.
"""

from sagaz.core.config import SagaConfig, configure, get_config
from sagaz.core.decorators import (
    Saga,
    SagaStepDefinition,
    action,
    compensate,
    forward_recovery,
    step,
)
from sagaz.core.exceptions import (
    MissingDependencyError,
    SagaCompensationError,
    SagaError,
    SagaExecutionError,
    SagaStepError,
    SagaTimeoutError,
)
from sagaz.core.hooks import (
    on_step_enter,
    on_step_failure,
    on_step_success,
    publish_on_compensate,
    publish_on_failure,
    publish_on_success,
)
from sagaz.core.listeners import (
    LoggingSagaListener,
    MetricsSagaListener,
    OutboxSagaListener,
    SagaListener,
    TracingSagaListener,
    default_listeners,
)
from sagaz.core.logger import NullLogger, get_logger, set_logger
from sagaz.core.saga import SagaContext, SagaResult, SagaStep
from sagaz.core.types import ParallelFailureStrategy, SagaResult, SagaStatus, SagaStepStatus

__all__ = [
    # Listeners
    "LoggingSagaListener",
    "MetricsSagaListener",
    # Exceptions
    "MissingDependencyError",
    # Logger
    "NullLogger",
    "OutboxSagaListener",
    # Types
    "ParallelFailureStrategy",
    # Decorators
    "Saga",
    "SagaCompensationError",
    # Config
    "SagaConfig",
    # Saga core
    "SagaContext",
    "SagaError",
    "SagaExecutionError",
    "SagaListener",
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
    "forward_recovery",
    "get_config",
    "get_logger",
    # Hooks
    "on_step_enter",
    "on_step_failure",
    "on_step_success",
    "publish_on_compensate",
    "publish_on_failure",
    "publish_on_success",
    "set_logger",
    "step",
]
