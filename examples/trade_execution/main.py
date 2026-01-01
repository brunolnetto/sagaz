"""
Trade Execution Saga Example

Demonstrates financial trading system with the declarative pattern.
"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class TradeExecutionSaga(Saga):
    """Production-ready saga for executing trades with multi-step validation and compensation."""
    
    saga_name = "trade-execution"

    def __init__(self, trade_id: int, symbol: str, quantity: float, price: float, user_id: int):
        super().__init__()
        self.trade_id = trade_id
        self.symbol = symbol
        self.quantity = quantity
        self.price = price
        self.user_id = user_id

    @action("reserve_funds")
    async def reserve_funds(self, ctx: SagaContext) -> dict[str, Any]:
        """Reserve funds for trade."""
        amount = self.quantity * self.price
        logger.info(f"Reserving ${amount} for user {self.user_id}")
        await asyncio.sleep(0.1)

        if amount > 100000:
            raise SagaStepError(f"Insufficient funds: need ${amount}")

        return {
            "reservation_id": f"RES-{self.trade_id}",
            "amount": amount,
            "user_id": self.user_id,
        }

    @compensate("reserve_funds")
    async def unreserve_funds(self, ctx: SagaContext) -> None:
        """Unreserve funds using reservation data from context."""
        logger.warning(f"Unreserving funds for trade {self.trade_id}")
        
        # Access reservation result from context
        reservation_id = ctx.get("reservation_id")
        amount = ctx.get("amount")
        if reservation_id:
            logger.info(f"Unreserving ${amount} (reservation: {reservation_id})")
        
        await asyncio.sleep(0.1)

    @action("execute_trade", depends_on=["reserve_funds"])
    async def execute_trade(self, ctx: SagaContext) -> dict[str, Any]:
        """Execute trade on exchange."""
        logger.info(f"Executing trade {self.trade_id}: {self.symbol} x{self.quantity} @ ${self.price}")
        await asyncio.sleep(0.3)

        return {
            "execution_id": f"EXE-{self.trade_id}",
            "symbol": self.symbol,
            "quantity": self.quantity,
            "executed_price": self.price,
            "status": "executed",
        }

    @compensate("execute_trade")
    async def cancel_trade(self, ctx: SagaContext) -> None:
        """Cancel trade on exchange using execution data from context."""
        logger.warning(f"Canceling trade {self.trade_id}")
        
        # Access trade execution result from context
        execution_id = ctx.get("execution_id")
        symbol = ctx.get("symbol")
        quantity = ctx.get("quantity")
        if execution_id:
            logger.info(f"Canceling execution {execution_id} for {symbol} x{quantity}")
        
        await asyncio.sleep(0.2)

    @action("update_position", depends_on=["execute_trade"])
    async def update_position(self, ctx: SagaContext) -> dict[str, Any]:
        """Update position in database."""
        logger.info(f"Updating position for trade {self.trade_id}")
        await asyncio.sleep(0.05)

        return {
            "position_updated": True,
            "trade_id": self.trade_id,
        }

    @compensate("update_position")
    async def revert_position(self, ctx: SagaContext) -> None:
        """Revert position update using position data from context."""
        logger.warning(f"Reverting position for trade {self.trade_id}")
        
        # Access position update result from context
        position_updated = ctx.get("position_updated")
        trade_id = ctx.get("trade_id")
        if position_updated:
            logger.info(f"Reverting position for trade {trade_id}")
        
        await asyncio.sleep(0.05)


class StrategyActivationSaga(Saga):
    """Strategy activation saga for trading systems."""
    
    saga_name = "strategy-activation"

    def __init__(self, strategy_id: int, user_id: int):
        super().__init__()
        self.strategy_id = strategy_id
        self.user_id = user_id

    @action("validate_strategy")
    async def validate_strategy(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate the strategy."""
        logger.info(f"Validating strategy {self.strategy_id}")
        await asyncio.sleep(0.05)
        return {"valid": True, "strategy_id": self.strategy_id}

    @action("validate_funds", depends_on=["validate_strategy"])
    async def validate_funds(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate sufficient funds."""
        logger.info(f"Validating funds for user {self.user_id}")
        await asyncio.sleep(0.05)
        return {"sufficient": True, "user_id": self.user_id}

    @action("activate_strategy", depends_on=["validate_funds"])
    async def activate_strategy(self, ctx: SagaContext) -> dict[str, Any]:
        """Activate the strategy."""
        logger.info(f"Activating strategy {self.strategy_id}")
        await asyncio.sleep(0.1)
        return {"strategy_id": self.strategy_id, "active": True}

    @compensate("activate_strategy")
    async def deactivate_strategy(self, ctx: SagaContext) -> None:
        """Deactivate the strategy."""
        logger.warning(f"Deactivating strategy {self.strategy_id}")
        strategy_id = ctx.get("strategy_id")
        if strategy_id:
            logger.info(f"Deactivating strategy {strategy_id}")
        await asyncio.sleep(0.05)

    @action("publish_event", depends_on=["activate_strategy"])
    async def publish_event(self, ctx: SagaContext) -> dict[str, Any]:
        """Publish activation event."""
        logger.info(f"Publishing activation event for strategy {self.strategy_id}")
        await asyncio.sleep(0.05)
        return {"event_id": f"evt_{self.strategy_id}", "published": True}


class SagaOrchestrator:
    """Simple saga orchestrator for managing multiple sagas."""
    
    def __init__(self):
        self.sagas: dict[str, Any] = {}
        
    async def execute_saga(self, saga):
        """Execute a saga and track it."""
        result = await saga.run({})
        self.sagas[saga._saga_id] = saga
        return result
        
    async def get_saga(self, saga_id: str):
        """Get a saga by ID."""
        return self.sagas.get(saga_id)
        
    async def get_statistics(self):
        """Get orchestrator statistics."""
        completed = sum(1 for s in self.sagas.values() if hasattr(s, '_context'))
        return {
            "total_sagas": len(self.sagas),
            "completed": completed,
            "executing": 0,
            "pending": 0,
        }


async def main():
    """Run the trade execution saga demo."""
    print("=" * 60)
    print("Trade Execution Saga Demo")
    print("=" * 60)

    saga = TradeExecutionSaga(
        trade_id=12345,
        symbol="AAPL",
        quantity=100,
        price=150.00,
        user_id=789,
    )

    result = await saga.run({"trade_id": saga.trade_id})

    print(f"\n{'✅' if result.get('saga_id') else '❌'} Trade Execution Result:")
    print(f"   Saga ID: {result.get('saga_id')}")
    print(f"   Trade ID: {result.get('trade_id')}")


if __name__ == "__main__":
    asyncio.run(main())
