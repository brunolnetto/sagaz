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

from sagaz.core.decorators._collection import DecoratorCollectionManager
from sagaz.core.decorators._execution import ExecutionEngine
from sagaz.core.decorators._ordering import _DecoratorOrderingMixin
from sagaz.core.decorators._pivot import _DecoratorPivotMixin
from sagaz.core.decorators._saga import Saga, SagaStepDefinition, logger
from sagaz.core.decorators._steps import (
    ForwardRecoveryMetadata,
    OnCompensateHook,
    OnEnterHook,
    OnExitHook,
    OnFailureHook,
    OnSuccessHook,
    StepMetadata,
    action,
    compensate,
    forward_recovery,
    step,
)
from sagaz.core.decorators._visualization import _DecoratorVisualizationMixin
from sagaz.core.execution.graph import CompensationType, SagaExecutionGraph

__all__ = [
    "ForwardRecoveryMetadata",
    "Saga",
    "SagaStepDefinition",
    "StepMetadata",
    "action",
    "compensate",
    "forward_recovery",
    "step",
]
