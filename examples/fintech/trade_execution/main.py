"""
Trade Execution Saga Example

Demonstrates financial trading system with the declarative pattern.
Data is passed through the run() method's initial context, not the constructor.
"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class TradeExecutionSaga(Saga):
    """
    Production-ready saga for executing trades with multi-step validation and compensation.
    
    This saga is stateless - all trade data is passed through the context
    via the run() method. The same saga instance can execute multiple trades.
    
    Expected context:
        - trade_id: int - Unique trade identifier
        - symbol: str - Stock/asset symbol
        - quantity: float - Number of units
        - price: float - Price per unit
        - user_id: int - Trader's user ID
    """

    saga_name = "trade-execution"

    @action("reserve_funds")
    async def reserve_funds(self, ctx: SagaContext) -> dict[str, Any]:
        """Reserve funds for trade."""
        trade_id = ctx.get("trade_id")
        user_id = ctx.get("user_id")
        quantity = ctx.get("quantity", 0)
        price = ctx.get("price", 0)
        
        amount = quantity * price
        logger.info(f"Reserving ${amount} for user {user_id}")
        await asyncio.sleep(0.1)

        if amount > 100000:
            msg = f"Insufficient funds: need ${amount}"
            raise SagaStepError(msg)

        return {
            "reservation_id": f"RES-{trade_id}",
            "amount": amount,
            "user_id": user_id,
        }

    @compensate("reserve_funds")
    async def unreserve_funds(self, ctx: SagaContext) -> None:
        """Unreserve funds using reservation data from context."""
        trade_id = ctx.get("trade_id")
        logger.warning(f"Unreserving funds for trade {trade_id}")

        # Access reservation result from context
        reservation_id = ctx.get("reservation_id")
        amount = ctx.get("amount")
        if reservation_id:
            logger.info(f"Unreserving ${amount} (reservation: {reservation_id})")

        await asyncio.sleep(0.1)

    @action("execute_trade", depends_on=["reserve_funds"])
    async def execute_trade(self, ctx: SagaContext) -> dict[str, Any]:
        """Execute trade on exchange."""
        trade_id = ctx.get("trade_id")
        symbol = ctx.get("symbol")
        quantity = ctx.get("quantity")
        price = ctx.get("price")
        
        logger.info(
            f"Executing trade {trade_id}: {symbol} x{quantity} @ ${price}"
        )
        await asyncio.sleep(0.3)

        return {
            "execution_id": f"EXE-{trade_id}",
            "symbol": symbol,
            "quantity": quantity,
            "executed_price": price,
            "status": "executed",
        }

    @compensate("execute_trade")
    async def cancel_trade(self, ctx: SagaContext) -> None:
        """Cancel trade on exchange using execution data from context."""
        trade_id = ctx.get("trade_id")
        logger.warning(f"Canceling trade {trade_id}")

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
        trade_id = ctx.get("trade_id")
        
        logger.info(f"Updating position for trade {trade_id}")
        await asyncio.sleep(0.05)

        return {
            "position_updated": True,
            "trade_id": trade_id,
        }

    @compensate("update_position")
    async def revert_position(self, ctx: SagaContext) -> None:
        """Revert position update using position data from context."""
        trade_id = ctx.get("trade_id")
        logger.warning(f"Reverting position for trade {trade_id}")

        # Access position update result from context
        position_updated = ctx.get("position_updated")
        if position_updated:
            logger.info(f"Reverting position for trade {trade_id}")

        await asyncio.sleep(0.05)


class StrategyActivationSaga(Saga):
    """
    Strategy activation saga for trading systems.
    
    Expected context:
        - strategy_id: int - Strategy to activate
        - user_id: int - User activating the strategy
    """

    saga_name = "strategy-activation"

    @action("validate_strategy")
    async def validate_strategy(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate the strategy."""
        strategy_id = ctx.get("strategy_id")
        
        logger.info(f"Validating strategy {strategy_id}")
        await asyncio.sleep(0.05)
        return {"valid": True, "strategy_id": strategy_id}

    @action("validate_funds", depends_on=["validate_strategy"])
    async def validate_funds(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate sufficient funds."""
        user_id = ctx.get("user_id")
        
        logger.info(f"Validating funds for user {user_id}")
        await asyncio.sleep(0.05)
        return {"sufficient": True, "user_id": user_id}

    @action("activate_strategy", depends_on=["validate_funds"])
    async def activate_strategy(self, ctx: SagaContext) -> dict[str, Any]:
        """Activate the strategy."""
        strategy_id = ctx.get("strategy_id")
        
        logger.info(f"Activating strategy {strategy_id}")
        await asyncio.sleep(0.1)
        return {"strategy_id": strategy_id, "active": True}

    @compensate("activate_strategy")
    async def deactivate_strategy(self, ctx: SagaContext) -> None:
        """Deactivate the strategy."""
        strategy_id = ctx.get("strategy_id")
        logger.warning(f"Deactivating strategy {strategy_id}")
        
        if strategy_id:
            logger.info(f"Deactivated strategy {strategy_id}")
        await asyncio.sleep(0.05)

    @action("publish_event", depends_on=["activate_strategy"])
    async def publish_event(self, ctx: SagaContext) -> dict[str, Any]:
        """Publish activation event."""
        strategy_id = ctx.get("strategy_id")
        
        logger.info(f"Publishing activation event for strategy {strategy_id}")
        await asyncio.sleep(0.05)
        return {"event_id": f"evt_{strategy_id}", "published": True}


class SagaOrchestrator:
    """Simple saga orchestrator for managing multiple sagas."""

    def __init__(self):
        self.sagas: dict[str, Any] = {}

    async def execute_saga(self, saga: Saga, context: dict[str, Any]):
        """Execute a saga and track it."""
        result = await saga.run(context)
        self.sagas[result.get("saga_id", "unknown")] = {
            "saga": saga,
            "result": result,
        }
        return result

    async def get_saga(self, saga_id: str):
        """Get a saga by ID."""
        return self.sagas.get(saga_id)

    async def get_statistics(self):
        """Get orchestrator statistics."""
        completed = sum(1 for s in self.sagas.values() if s["result"].get("success"))
        return {
            "total_sagas": len(self.sagas),
            "completed": completed,
            "failed": len(self.sagas) - completed,
        }


async def main():
    """Run the trade execution saga demo."""
    print("=" * 60)
    print("Trade Execution Saga Demo")
    print("=" * 60)

    # Create a reusable saga instance
    saga = TradeExecutionSaga()

    # Execute first trade
    result1 = await saga.run({
        "trade_id": 12345,
        "symbol": "AAPL",
        "quantity": 100,
        "price": 150.00,
        "user_id": 789,
    })

    print(f"\n{'✅' if result1.get('saga_id') else '❌'} First Trade Result:")
    print(f"   Saga ID: {result1.get('saga_id')}")
    print(f"   Trade ID: {result1.get('trade_id')}")
    
    # Demonstrate reusability - same saga, different trade
    print("\n--- Executing second trade with same saga instance ---\n")
    
    result2 = await saga.run({
        "trade_id": 67890,
        "symbol": "GOOGL",
        "quantity": 50,
        "price": 175.00,
        "user_id": 789,
    })

    print(f"\n{'✅' if result2.get('saga_id') else '❌'} Second Trade Result:")
    print(f"   Saga ID: {result2.get('saga_id')}")
    print(f"   Trade ID: {result2.get('trade_id')}")


if __name__ == "__main__":
    asyncio.run(main())
