# Cryptocurrency Exchange Saga

**Category:** Fintech/Blockchain  
**Pivot Type:** Blockchain Immutability

## Description

This saga demonstrates a cryptocurrency exchange flow where broadcasting to the blockchain represents the **point of no return**. Once a transaction is in the mempool, it cannot be reversed - only forward recovery strategies apply.

## Saga Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│ validate_trade  │ ──→ │  reserve_balance │ ──→ │ execute_exchange   │
│ (reversible)    │     │  (reversible)    │     │ (internal ledger)  │
└─────────────────┘     └──────────────────┘     └─────────┬──────────┘
                                                           │
                        ┌──────────────────────────────────┘
                        ↓
┌─────────────────────────────┐     ┌───────────────────┐     ┌─────────────────┐
│ broadcast_to_blockchain     │ ──→ │ wait_confirmation │ ──→ │ update_balances │
│ 🔒 PIVOT (once broadcast,   │     │ (forward only)    │     │ (forward only)  │
│   cannot undo on-chain)     │     │                   │     │                 │
└─────────────────────────────┘     └───────────────────┘     └─────────────────┘
```

## Pivot Step: `broadcast_to_blockchain`

Once a transaction is broadcast to the blockchain network:

### Why It's Irreversible

- Transaction is in the mempool, visible to miners
- Even if not confirmed, it may eventually be mined
- Cannot be "cancelled" - only superseded with higher fee (RBF)
- On-chain data is immutable

### What Happens After Pivot

- All ancestor steps become "tainted" (cannot compensate)
- Only forward recovery strategies available
- Must wait for confirmation or use RBF to speed up

## Forward Recovery Strategies

| Scenario | Strategy | Action |
|----------|----------|--------|
| Confirmation timeout | RETRY | Check status again |
| Network congestion | RETRY_WITH_ALTERNATE | Send RBF with higher gas |
| Persistent failure | MANUAL_INTERVENTION | Escalate to support |

## Usage

```python
from examples.fintech.crypto_exchange import CryptoExchangeSaga
from decimal import Decimal

saga = CryptoExchangeSaga()

result = await saga.run({
    "trade_id": "TRADE-001",
    "user_id": "USER-456",
    "from_currency": "BTC",
    "to_currency": "ETH",
    "amount": Decimal("0.5"),
    "destination_wallet": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bAcE",
    "network": "ethereum",
})
```

## Context Schema

| Field | Type | Description |
|-------|------|-------------|
| `trade_id` | str | Unique trade identifier |
| `user_id` | str | User performing the trade |
| `from_currency` | str | Source currency (e.g., "BTC") |
| `to_currency` | str | Destination currency (e.g., "ETH") |
| `amount` | Decimal | Amount to exchange |
| `destination_wallet` | str | Wallet for receiving funds |
| `network` | str | Blockchain network (e.g., "ethereum") |

## Running the Example

```bash
# Direct execution
python examples/fintech/crypto_exchange/main.py

# Or via sagaz CLI
sagaz examples run fintech/crypto_exchange
```

## Key Concepts Demonstrated

1. **Blockchain Immutability**: Operations on-chain cannot be reversed
2. **Pivot Recognition**: The broadcast step is clearly marked as pivot
3. **Forward Recovery**: Post-pivot failures use retry/escalation strategies
4. **Two-Phase Transactions**: Internal ledger vs. on-chain operations
