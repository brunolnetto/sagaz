# Property Closing Saga

**Category:** Real Estate  
**Pivot Type:** Legal Commitment

## Description

This saga demonstrates a real estate closing process with **multiple pivot points**. Both escrow release (financial commitment) and deed recording (legal transfer) represent points of no return that cannot be easily reversed.

## Saga Flow

```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ title_search      │ ──→ │ appraisal_review│ ──→ │ clear_contingencies │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
                    ┌─────────────────┐
                    │ final_walkthrough│
                    │ (reversible)    │
                    └────────┬────────┘
                             │
┌────────────────────────────┘
↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ release_escrow              │ ──→ │ record_deed           │ ──→ │ transfer_keys │
│ 🔒 PIVOT 1 (funds released, │     │ 🔒 PIVOT 2 (ownership │     │ (forward only)│
│   seller has money)         │     │   legally transferred)│     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

## Pivot Steps

### Pivot 1: `release_escrow`

Once escrow is released:

- Funds are wired to seller's account
- Financial commitment is made
- Reversal requires legal action

### Pivot 2: `record_deed`

Once deed is recorded:

- Ownership is legally transferred
- Public records updated
- Reversal requires new sale transaction

### Critical Scenario: Between Pivots

The most dangerous situation is when Pivot 1 completes but Pivot 2 fails:
- Seller HAS the money
- Buyer DOES NOT have legal ownership

Forward recovery is critical to protect all parties.

## Forward Recovery Strategies

| Scenario | Strategy | Action |
|----------|----------|--------|
| County system down | RETRY | Wait and retry recording |
| Document issue | RETRY_WITH_ALTERNATE | Correct and resubmit |
| Persistent failure | MANUAL_INTERVENTION | Title company escalates |

## Usage

```python
from examples.real_estate.property_closing import PropertyClosingSaga
from decimal import Decimal

saga = PropertyClosingSaga()

result = await saga.run({
    "transaction_id": "CLOSE-2026-001",
    "property_id": "PROP-123456",
    "buyer_name": "Alice Johnson",
    "seller_name": "Bob Smith",
    "purchase_price": Decimal("550000"),
    "escrow_amount": Decimal("550000"),
    "seller_account": "ACCT-SELLER-001",
    "county": "San Francisco County",
})
```

## Context Schema

| Field | Type | Description |
|-------|------|-------------|
| `transaction_id` | str | Unique closing transaction ID |
| `property_id` | str | Property identifier |
| `buyer_name` | str | Buyer's legal name |
| `seller_name` | str | Seller's legal name |
| `purchase_price` | Decimal | Purchase price |
| `escrow_amount` | Decimal | Total escrow amount |
| `seller_account` | str | Seller's bank account |
| `county` | str | County for deed recording |

## Running the Example

```bash
python examples/real_estate/property_closing/main.py
```

## Key Concepts Demonstrated

1. **Multiple Pivot Points**: Two sequential irreversible actions
2. **Legal Commitment**: Deed recording as public record change
3. **Financial Commitment**: Escrow release as funds transfer
4. **Title Insurance**: Protecting against title defects
5. **Closing Coordination**: Multiple parties and systems
