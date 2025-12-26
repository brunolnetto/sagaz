from typing import Any, Callable
import asyncio
import logging

from sagaz import (
    ClassicSaga,
    SagaContext,
    SagaStatus,
    SagaResult,
)

logger = logging.getLogger(__name__)

# ============================================
# EXAMPLE: TRADE EXECUTION SAGA
# ============================================


class TradeExecutionSaga(ClassicSaga):
    """Production-ready saga for executing trades with multi-step validation and compensation"""

    def __init__(self, trade_id: int, symbol: str, quantity: float, price: float, user_id: int):
        super().__init__(name=f"TradeExecutionSaga-{trade_id}", version="2.0")
        self.trade_id = trade_id
        self.symbol = symbol
        self.quantity = quantity
        self.price = price
        self.user_id = user_id

    async def build(
        self,
        reserve_funds_action: Callable,
        execute_trade_action: Callable,
        update_position_action: Callable,
        unreserve_funds_compensation: Callable,
        cancel_trade_compensation: Callable,
        revert_position_compensation: Callable,
    ) -> None:
        """Build saga with provided actions"""

        # Step 1: Reserve funds for trade
        await self.add_step(
            name="reserve_funds",
            action=lambda ctx: reserve_funds_action(self.user_id, self.quantity * self.price, ctx),
            compensation=lambda result, ctx: unreserve_funds_compensation(
                self.user_id, result, ctx
            ),
            timeout=10.0,
            max_retries=3,
        )

        # Step 2: Execute trade on exchange
        await self.add_step(
            name="execute_trade",
            action=lambda ctx: execute_trade_action(
                self.trade_id, self.symbol, self.quantity, self.price, ctx
            ),
            compensation=lambda result, ctx: cancel_trade_compensation(self.trade_id, result, ctx),
            timeout=30.0,
            max_retries=2,
        )

        # Step 3: Update position in database
        await self.add_step(
            name="update_position",
            action=lambda ctx: update_position_action(
                self.trade_id, self.quantity, self.price, ctx
            ),
            compensation=lambda result, ctx: revert_position_compensation(self.trade_id, ctx),
            timeout=5.0,
            max_retries=3,
        )


# ============================================
# STRATEGY ACTIVATION SAGA
# ============================================


class StrategyActivationSaga(ClassicSaga):
    """Production-ready saga for activating trading strategies"""

    def __init__(self, strategy_id: int, user_id: int):
        super().__init__(name=f"StrategyActivationSaga-{strategy_id}", version="2.0")
        self.strategy_id = strategy_id
        self.user_id = user_id

    async def build(
        self,
        validate_strategy_action: Callable,
        validate_funds_action: Callable,
        activate_strategy_action: Callable,
        publish_event_action: Callable,
        deactivate_strategy_compensation: Callable,
    ) -> None:
        """Build saga with provided actions"""

        # Step 1: Validate strategy configuration
        await self.add_step(
            name="validate_strategy",
            action=lambda ctx: validate_strategy_action(self.strategy_id, ctx),
            timeout=5.0,
        )

        # Step 2: Validate user has sufficient funds
        await self.add_step(
            name="validate_funds",
            action=lambda ctx: validate_funds_action(self.user_id, self.strategy_id, ctx),
            timeout=5.0,
        )

        # Step 3: Activate the strategy
        await self.add_step(
            name="activate_strategy",
            action=lambda ctx: activate_strategy_action(self.strategy_id, self.user_id, ctx),
            compensation=lambda result, ctx: deactivate_strategy_compensation(
                self.strategy_id, ctx
            ),
            timeout=10.0,
            max_retries=3,
        )

        # Step 4: Publish event (no compensation needed - idempotent)
        await self.add_step(
            name="publish_event",
            action=lambda ctx: publish_event_action(self.strategy_id, self.user_id, ctx),
            timeout=5.0,
        )


# ============================================
# SAGA ORCHESTRATOR
# ============================================


class SagaOrchestrator:
    """
    Production-ready orchestrator for managing and tracking multiple sagas
    Thread-safe with proper async support
    """

    def __init__(self):
        self.sagas: dict[str, ClassicSaga] = {}
        self._lock = asyncio.Lock()

    async def execute_saga(self, saga: ClassicSaga) -> SagaResult:
        """Execute a saga and track it"""
        async with self._lock:
            self.sagas[saga.saga_id] = saga

        result = await saga.execute()

        logger.info(
            f"Saga {saga.name} [{saga.saga_id}] finished with status: {result.status.value}"
        )

        return result

    async def get_saga(self, saga_id: str) -> ClassicSaga | None:
        """Get saga by ID"""
        async with self._lock:
            return self.sagas.get(saga_id)

    async def get_saga_status(self, saga_id: str) -> dict[str, Any] | None:
        """Get status of a saga by ID"""
        saga = await self.get_saga(saga_id)
        return saga.get_status() if saga else None

    async def get_all_sagas_status(self) -> list[dict[str, Any]]:
        """Get status of all sagas"""
        async with self._lock:
            return [saga.get_status() for saga in self.sagas.values()]

    async def count_by_status(self, status: SagaStatus) -> int:
        """Count sagas by status"""
        async with self._lock:
            return sum(1 for saga in self.sagas.values() if saga.status == status)

    async def count_completed(self) -> int:
        """Count completed sagas"""
        return await self.count_by_status(SagaStatus.COMPLETED)

    async def count_failed(self) -> int:
        """Count failed sagas (unrecoverable)"""
        return await self.count_by_status(SagaStatus.FAILED)

    async def count_rolled_back(self) -> int:
        """Count rolled back sagas (recovered)"""
        return await self.count_by_status(SagaStatus.ROLLED_BACK)

    async def get_statistics(self) -> dict[str, Any]:
        """Get orchestrator statistics"""
        from collections import Counter
        
        async with self._lock:
            counts = Counter(saga.status for saga in self.sagas.values())
            return {
                "total_sagas": len(self.sagas),
                "completed": counts.get(SagaStatus.COMPLETED, 0),
                "rolled_back": counts.get(SagaStatus.ROLLED_BACK, 0),
                "failed": counts.get(SagaStatus.FAILED, 0),
                "executing": counts.get(SagaStatus.EXECUTING, 0),
                "pending": counts.get(SagaStatus.PENDING, 0),
            }
