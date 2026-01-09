# SIM Provisioning Saga

This example demonstrates a **SIM activation pivot point** in telecom provisioning. Once the SIM is activated on the network, the subscription is live and billing starts.

## Pivot Point

**Step:** `activate_sim`

Once the SIM is activated:
- The phone number is live on the network
- Billing starts immediately
- Network resources are allocated
- The customer can make/receive calls

## Saga Steps

```
┌─────────────────────────────────────────────────────────────────┐
│                     REVERSIBLE ZONE                              │
├─────────────────────────────────────────────────────────────────┤
│  validate_order → verify_identity → assign_msisdn → provision_hlr│
│                                                                  │
│  Can cancel order before activation                             │
├─────────────────────────────────────────────────────────────────┤
│                    ↓ PIVOT BOUNDARY ↓                            │
├─────────────────────────────────────────────────────────────────┤
│                     COMMITTED ZONE                               │
│                                                                  │
│  🔒 activate_sim (PIVOT) → configure_services → send_welcome    │
│                                                                  │
│  SIM active, billing started - forward recovery only            │
└─────────────────────────────────────────────────────────────────┘
```

## Forward Recovery

If service configuration fails after activation:
- **RETRY**: Retry provisioning system (may be temporarily down)
- **MANUAL_INTERVENTION**: Network operations team handles manually

## Running the Example

```bash
cd examples/telecom/sim_provisioning
python main.py
```

## Key Features Demonstrated

- `@action("activate_sim", pivot=True)` - Marks activation as irreversible
- `@forward_recovery("configure_services")` - Handles service config failures
- Network state change that starts billing

## Business Context

In telecom provisioning:
- KYC (Know Your Customer) is required for compliance
- MSISDN (phone number) is a scarce resource
- HLR (Home Location Register) is the source of truth
- Activation starts the billing cycle
- Service configuration defines the customer's plan
- Welcome messages confirm successful provisioning
