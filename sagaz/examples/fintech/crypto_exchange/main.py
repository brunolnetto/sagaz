"""
Cryptocurrency Exchange Saga Example

Demonstrates blockchain immutability as a pivot point. Once a transaction
is broadcast to the blockchain, it cannot be reversed - only forward
recovery strategies apply.

Pivot Step: broadcast_to_blockchain
    Once transaction is in the mempool, it may eventually be mined.
    Cannot be "cancelled" - only superseded with higher fee (RBF).

Forward Recovery:
    - Confirmation timeout: Retry with higher gas, send RBF transaction
    - Balance update failure: Reconcile from blockchain state
"""

import asyncio
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from sagaz import Saga, SagaContext, action, compensate, forward_recovery
from sagaz.exceptions import SagaStepError
from sagaz.pivot import RecoveryAction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Simulation Helpers
# =============================================================================


class BlockchainSimulator:
    """Simulates blockchain interactions for demo purposes."""

    @staticmethod
    async def validate_wallet(wallet: str) -> bool:
        """Validate wallet address format."""
        await asyncio.sleep(0.05)
        return wallet.startswith("0x") and len(wallet) == 42

    @staticmethod
    async def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
        """Get simulated exchange rate."""
        await asyncio.sleep(0.05)
        rates = {
            ("BTC", "ETH"): Decimal("15.5"),
            ("ETH", "BTC"): Decimal("0.065"),
            ("BTC", "USDT"): Decimal("45000.00"),
            ("ETH", "USDT"): Decimal("2900.00"),
        }
        return rates.get((from_currency, to_currency), Decimal("1.0"))

    @staticmethod
    async def broadcast_transaction(
        tx_data: dict,
        network: str,
    ) -> dict:
        """Broadcast transaction to blockchain network."""
        await asyncio.sleep(0.3)  # Simulate network latency

        # Simulate occasional failures
        import random

        if random.random() < 0.1:  # 10% failure rate
            msg = "Failed to broadcast transaction: Network congestion"
            raise SagaStepError(msg)

        return {
            "tx_hash": f"0x{'a' * 64}",
            "network": network,
            "broadcast_time": datetime.now().isoformat(),
            "gas_price": "25 gwei",
        }

    @staticmethod
    async def wait_for_confirmations(
        tx_hash: str,
        required_confirmations: int = 6,
    ) -> dict:
        """Wait for blockchain confirmations."""
        await asyncio.sleep(0.5)  # Simulate waiting for blocks

        return {
            "tx_hash": tx_hash,
            "confirmations": required_confirmations,
            "block_number": 18500000,
            "status": "confirmed",
        }


# =============================================================================
# Saga Definition
# =============================================================================


class CryptoExchangeSaga(Saga):
    """
    Cryptocurrency exchange saga with blockchain pivot.

    This saga demonstrates the irreversibility of blockchain transactions.
    Once a transaction is broadcast, traditional rollback is impossible.
    Forward recovery strategies must be used for post-pivot failures.

    Expected context:
        - trade_id: str - Unique trade identifier
        - user_id: str - User performing the trade
        - from_currency: str - Source currency (e.g., "BTC")
        - to_currency: str - Destination currency (e.g., "ETH")
        - amount: Decimal - Amount to exchange
        - destination_wallet: str - Wallet for receiving funds
        - network: str - Blockchain network (e.g., "ethereum")
    """

    saga_name = "crypto-exchange"

    # === REVERSIBLE ZONE ===

    @action("validate_trade")
    async def validate_trade(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate trade parameters and wallet address."""
        trade_id = ctx.get("trade_id")
        destination_wallet = ctx.get("destination_wallet")

        logger.info(f"🔍 [{trade_id}] Validating trade parameters...")

        # Validate wallet
        if not await BlockchainSimulator.validate_wallet(destination_wallet):
            msg = f"Invalid wallet address: {destination_wallet}"
            raise SagaStepError(msg)

        # Get exchange rate
        from_currency = ctx.get("from_currency")
        to_currency = ctx.get("to_currency")
        rate = await BlockchainSimulator.get_exchange_rate(from_currency, to_currency)

        amount = ctx.get("amount", Decimal("0"))
        output_amount = amount * rate

        logger.info(
            f"✅ [{trade_id}] Trade validated: "
            f"{amount} {from_currency} → {output_amount:.4f} {to_currency}"
        )

        return {
            "exchange_rate": str(rate),
            "output_amount": str(output_amount),
            "validation_time": datetime.now().isoformat(),
        }

    @compensate("validate_trade")
    async def invalidate_trade(self, ctx: SagaContext) -> None:
        """Cancel trade validation (no-op, just logging)."""
        trade_id = ctx.get("trade_id")
        logger.warning(f"↩️ [{trade_id}] Invalidating trade validation...")
        await asyncio.sleep(0.05)

    @action("reserve_balance", depends_on=["validate_trade"])
    async def reserve_balance(self, ctx: SagaContext) -> dict[str, Any]:
        """Reserve funds in user's internal wallet."""
        trade_id = ctx.get("trade_id")
        user_id = ctx.get("user_id")
        amount = ctx.get("amount")
        from_currency = ctx.get("from_currency")

        logger.info(f"💰 [{trade_id}] Reserving {amount} {from_currency} for {user_id}...")
        await asyncio.sleep(0.1)

        reservation_id = f"RES-{trade_id}"

        logger.info(f"✅ [{trade_id}] Balance reserved: {reservation_id}")

        return {
            "reservation_id": reservation_id,
            "reserved_amount": str(amount),
            "reserved_currency": from_currency,
        }

    @compensate("reserve_balance")
    async def release_balance(self, ctx: SagaContext) -> None:
        """Release reserved funds back to user's wallet."""
        trade_id = ctx.get("trade_id")
        reservation_id = ctx.get("reservation_id")

        logger.warning(f"↩️ [{trade_id}] Releasing reservation {reservation_id}...")
        await asyncio.sleep(0.1)
        logger.info(f"✅ [{trade_id}] Balance released")

    @action("execute_internal_exchange", depends_on=["reserve_balance"])
    async def execute_internal_exchange(self, ctx: SagaContext) -> dict[str, Any]:
        """Execute exchange on internal ledger."""
        trade_id = ctx.get("trade_id")
        output_amount = ctx.get("output_amount", "0")
        to_currency = ctx.get("to_currency")

        logger.info(f"🔄 [{trade_id}] Executing internal exchange...")
        await asyncio.sleep(0.1)

        internal_tx_id = f"INT-{trade_id}"

        logger.info(
            f"✅ [{trade_id}] Internal exchange complete: "
            f"{output_amount} {to_currency} ready for withdrawal"
        )

        return {
            "internal_tx_id": internal_tx_id,
            "exchange_status": "completed",
        }

    @compensate("execute_internal_exchange")
    async def reverse_internal_exchange(self, ctx: SagaContext) -> None:
        """Reverse internal ledger exchange."""
        trade_id = ctx.get("trade_id")
        internal_tx_id = ctx.get("internal_tx_id")

        logger.warning(f"↩️ [{trade_id}] Reversing internal exchange {internal_tx_id}...")
        await asyncio.sleep(0.1)
        logger.info(f"✅ [{trade_id}] Internal exchange reversed")

    # === PIVOT STEP ===

    @action("broadcast_to_blockchain", depends_on=["execute_internal_exchange"], pivot=True)
    async def broadcast_to_blockchain(self, ctx: SagaContext) -> dict[str, Any]:
        """
        🔒 PIVOT STEP: Broadcast transaction to blockchain.

        Once this step completes, the transaction is in the mempool and
        may eventually be mined. Traditional rollback is IMPOSSIBLE.
        Forward recovery strategies must be used for subsequent failures.
        """
        trade_id = ctx.get("trade_id")
        output_amount = ctx.get("output_amount", "0")
        to_currency = ctx.get("to_currency")
        destination_wallet = ctx.get("destination_wallet")
        network = ctx.get("network", "ethereum")

        logger.info(f"🔒 [{trade_id}] PIVOT: Broadcasting to blockchain...")

        tx_data = {
            "to": destination_wallet,
            "value": output_amount,
            "currency": to_currency,
            "trade_id": trade_id,
        }

        result = await BlockchainSimulator.broadcast_transaction(tx_data, network)

        logger.info(f"✅ [{trade_id}] Transaction broadcast! TX Hash: {result['tx_hash'][:20]}...")

        return {
            "tx_hash": result["tx_hash"],
            "broadcast_time": result["broadcast_time"],
            "gas_price": result["gas_price"],
            "pivot_reached": True,  # Mark that we've passed the point of no return
        }

    # Note: No compensation for broadcast_to_blockchain - it's a pivot step!
    # If we need to "undo", we would need a separate reversal transaction.

    # === COMMITTED ZONE (Forward Recovery Only) ===

    @action("wait_confirmations", depends_on=["broadcast_to_blockchain"])
    async def wait_confirmations(self, ctx: SagaContext) -> dict[str, Any]:
        """Wait for blockchain confirmations."""
        trade_id = ctx.get("trade_id")
        tx_hash = ctx.get("tx_hash")

        logger.info(f"⏳ [{trade_id}] Waiting for confirmations...")

        result = await BlockchainSimulator.wait_for_confirmations(tx_hash)

        logger.info(
            f"✅ [{trade_id}] Transaction confirmed! "
            f"{result['confirmations']} confirmations at block {result['block_number']}"
        )

        return {
            "confirmations": result["confirmations"],
            "block_number": result["block_number"],
            "confirmation_status": result["status"],
        }

    @forward_recovery("wait_confirmations")
    async def handle_confirmation_timeout(
        self, ctx: SagaContext, error: Exception
    ) -> RecoveryAction:
        """
        Forward recovery for confirmation timeout.

        Strategies:
        1. RETRY - Check transaction status again
        2. RETRY_WITH_ALTERNATE - Send replace-by-fee (RBF) with higher gas
        3. MANUAL_INTERVENTION - Escalate for manual resolution
        """
        retry_count = ctx.get("confirmation_retry_count", 0)

        if retry_count < 3:
            ctx.set("confirmation_retry_count", retry_count + 1)
            logger.info("🔄 Retrying confirmation check...")
            return RecoveryAction.RETRY

        # Try RBF with higher gas
        if ctx.get("rbf_attempted") is None:
            ctx.set("rbf_attempted", True)
            ctx.set("gas_multiplier", 1.5)
            logger.info("⚡ Attempting replace-by-fee with higher gas...")
            return RecoveryAction.RETRY_WITH_ALTERNATE

        logger.error("❌ All recovery attempts exhausted. Manual intervention required.")
        return RecoveryAction.MANUAL_INTERVENTION

    @action("update_balances", depends_on=["wait_confirmations"])
    async def update_balances(self, ctx: SagaContext) -> dict[str, Any]:
        """Update user balances after confirmed transaction."""
        trade_id = ctx.get("trade_id")
        user_id = ctx.get("user_id")

        logger.info(f"📊 [{trade_id}] Updating balances for {user_id}...")
        await asyncio.sleep(0.1)

        logger.info(f"✅ [{trade_id}] Balances updated!")

        return {
            "balance_updated": True,
            "completion_time": datetime.now().isoformat(),
        }


# =============================================================================
# Demo Scenarios
# =============================================================================


async def main():
    """Run the crypto exchange saga demo."""

    saga = CryptoExchangeSaga()

    # Scenario 1: Successful trade

    await saga.run(
        {
            "trade_id": "TRADE-001",
            "user_id": "USER-456",
            "from_currency": "BTC",
            "to_currency": "ETH",
            "amount": Decimal("0.5"),
            "destination_wallet": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bAcE",
            "network": "ethereum",
        }
    )

    # Scenario 2: Pre-pivot failure (rollback)

    try:
        await saga.run(
            {
                "trade_id": "TRADE-002",
                "user_id": "USER-789",
                "from_currency": "ETH",
                "to_currency": "BTC",
                "amount": Decimal("5.0"),
                "destination_wallet": "invalid-wallet",  # Invalid!
                "network": "bitcoin",
            }
        )
    except SagaStepError:
        pass

    # Scenario 3: Description of post-pivot behavior


if __name__ == "__main__":
    asyncio.run(main())
