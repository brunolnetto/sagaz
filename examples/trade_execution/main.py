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
        """Unreserve funds."""
        logger.warning(f"Unreserving funds for trade {self.trade_id}")
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
        """Cancel trade on exchange."""
        logger.warning(f"Canceling trade {self.trade_id}")
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
        """Revert position update."""
        logger.warning(f"Reverting position for trade {self.trade_id}")
        await asyncio.sleep(0.05)


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
