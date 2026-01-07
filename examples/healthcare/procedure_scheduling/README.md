# Medical Procedure Scheduling Saga

This example demonstrates a **procedure confirmation pivot point** in healthcare scheduling. Once the procedure is confirmed, operating room time and surgical staff are committed.

## Pivot Point

**Step:** `confirm_procedure`

Once the procedure is confirmed:
- Operating room time is blocked
- Surgical staff schedules are locked
- Patient has been notified and is preparing
- Cancellation has significant resource implications

## Saga Steps

```
┌─────────────────────────────────────────────────────────────────┐
│                     REVERSIBLE ZONE                              │
├─────────────────────────────────────────────────────────────────┤
│  verify_authorization → check_patient_history → reserve_or_time  │
│               → assign_staff                                     │
│                                                                  │
│  Can cancel without major resource impact                       │
├─────────────────────────────────────────────────────────────────┤
│                    ↓ PIVOT BOUNDARY ↓                            │
├─────────────────────────────────────────────────────────────────┤
│                     COMMITTED ZONE                               │
│                                                                  │
│  🔒 confirm_procedure (PIVOT) → order_supplies → send_prep      │
│                                                                  │
│  Resources committed - forward recovery only                     │
└─────────────────────────────────────────────────────────────────┘
```

## Forward Recovery

If supplies are unavailable after confirmation:
- **RETRY_WITH_ALTERNATE**: Try alternate supplier
- **MANUAL_INTERVENTION**: Postpone or find substitutes

## Running the Example

```bash
cd examples/healthcare/procedure_scheduling
python main.py
```

## Key Features Demonstrated

- `@action("confirm_procedure", pivot=True)` - Marks confirmation as irreversible
- `@forward_recovery("order_supplies")` - Handles supply chain issues
- Resource commitment with patient care implications

## Business Context

In healthcare scheduling:
- Insurance authorization must be verified
- Patient medical history affects procedure planning
- OR (Operating Room) time is a scarce, expensive resource
- Surgical staff must be available and qualified
- Supplies must be ordered and sterilized
- Patient needs fasting and preparation instructions
- Cancellations waste significant hospital resources
