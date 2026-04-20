# Rental Application Processing Saga

This example demonstrates a **deposit charge pivot point** in a rental application workflow. Once the deposit is charged, the applicant is financially committed to the application.

## Pivot Point

**Step:** `charge_deposit`

Once the deposit is charged to the applicant's payment method:
- The applicant is financially committed
- The property is effectively reserved
- Refunds may be subject to terms and conditions

## Saga Steps

```
┌─────────────────────────────────────────────────────────────────┐
│                     REVERSIBLE ZONE                              │
├─────────────────────────────────────────────────────────────────┤
│  validate_application → verify_income → run_credit_check         │
│                                                                  │
│  Can fully rollback if any step fails                           │
├─────────────────────────────────────────────────────────────────┤
│                    ↓ PIVOT BOUNDARY ↓                            │
├─────────────────────────────────────────────────────────────────┤
│                     COMMITTED ZONE                               │
│                                                                  │
│  🔒 charge_deposit (PIVOT) → reserve_unit → generate_lease      │
│                                                                  │
│  Forward recovery only after deposit charged                     │
└─────────────────────────────────────────────────────────────────┘
```

## Forward Recovery

If unit reservation fails after deposit is charged:
- **RETRY**: Attempt reservation again (system may be temporarily unavailable)
- **RETRY_WITH_ALTERNATE**: Offer an alternate unit from available inventory
- **MANUAL_INTERVENTION**: Leasing agent manually resolves the situation

## Running the Example

```bash
cd examples/real_estate/rental_application
python main.py
```

## Key Features Demonstrated

- `@action("charge_deposit", pivot=True)` - Marks the deposit charge as irreversible
- `@forward_recovery("reserve_unit")` - Handles failures after pivot
- `RecoveryAction.RETRY_WITH_ALTERNATE` - Offers alternate units

## Business Context

In property rental:
- Credit checks cost money and are logged
- Deposits are real financial transactions
- Once charged, refunds have policy implications
- Units become reserved and removed from available inventory
