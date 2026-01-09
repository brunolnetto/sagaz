# Mobile Number Porting Saga

**Category:** Telecommunications  
**Pivot Type:** Regulatory Action

## Description

This saga demonstrates the FCC-regulated mobile number porting process where updating the NPAC (Number Portability Administration Center) database is the **point of no return**. Once a number is ported in NPAC, it's officially transferred and reversing requires a new full port request.

## Saga Flow

```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│submit_port_request│ ──→ │validate_customer│ ──→ │ verify_with_donor   │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ execute_port                │ ──→ │ activate_new_carrier  │ ──→ │ update_routing│
│ 🔒 PIVOT (NPAC updated,     │     │ (forward only)        │     │ (forward only)│
│   number officially ported) │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────┬───────┘
                                                                          │
                                                              ┌───────────┘
                                                              ↓
                                                    ┌─────────────────┐
                                                    │ notify_customer │
                                                    │ (forward only)  │
                                                    └─────────────────┘
```

## Pivot Step: `execute_port`

Once the NPAC database is updated:

### Why It's Irreversible

- Number officially registered with new carrier in national database
- FCC-regulated action with legal implications
- All carriers notified of the new assignment
- Reversal requires filing a new port request

### What Happens After Pivot

- Number can receive calls (routing tables updated)
- Must complete activation for full service
- Cannot roll back - only forward or manual intervention

## Forward Recovery Strategies

| Scenario | Strategy | Action |
|----------|----------|--------|
| Provisioning delay | RETRY | Wait and retry activation |
| SIM not ready | RETRY_WITH_ALTERNATE | Expedite SIM or use eSIM |
| Network issues | MANUAL_INTERVENTION | NOC manual activation |

## Usage

```python
from examples.telecom.number_porting import MobileNumberPortingSaga

saga = MobileNumberPortingSaga()

result = await saga.run({
    "port_request_id": "PORT-2026-001",
    "phone_number": "+1-555-123-4567",
    "customer_name": "John Doe",
    "account_number": "ACCT-987654",
    "account_pin": "1234",
    "donor_carrier": "OldMobile",
    "new_carrier": "NewTelco",
    "customer_email": "john.doe@email.com",
    "sim_iccid": "8901260123456789012",
})
```

## Context Schema

| Field | Type | Description |
|-------|------|-------------|
| `port_request_id` | str | Unique port request identifier |
| `phone_number` | str | Number being ported |
| `customer_name` | str | Customer's full name |
| `account_number` | str | Account with donor carrier |
| `account_pin` | str | Account PIN for verification |
| `donor_carrier` | str | Current carrier (losing) |
| `new_carrier` | str | New carrier (gaining) |
| `customer_email` | str | Customer email |
| `sim_iccid` | str | New SIM card ICCID |

## Running the Example

```bash
python examples/telecom/number_porting/main.py
```

## Key Concepts Demonstrated

1. **Regulatory Compliance**: FCC-mandated porting process
2. **NPAC Integration**: National number portability database
3. **Multi-Carrier Coordination**: Donor and recipient carriers
4. **Location Routing Number (LRN)**: How calls find ported numbers
5. **Activation vs. Porting**: Two distinct but linked processes
