# Power Grid Switching Saga

This example demonstrates a **grid connection pivot point** in power system operations. Once the breaker is closed, power is flowing and cannot simply be "undone" - it requires a safe disconnect procedure.

## Pivot Point

**Step:** `close_breaker`

Once the breaker is closed:
- Power is actively flowing through the circuit
- Equipment and loads are energized
- Opening the breaker under load risks arc flash
- Proper isolation procedures must be followed

## Saga Steps

```
┌─────────────────────────────────────────────────────────────────┐
│                     REVERSIBLE ZONE                              │
├─────────────────────────────────────────────────────────────────┤
│  validate_switch_request → notify_operators → verify_isolation   │
│                                                                  │
│  Can safely abort before energizing                             │
├─────────────────────────────────────────────────────────────────┤
│                    ↓ PIVOT BOUNDARY ↓                            │
├─────────────────────────────────────────────────────────────────┤
│                     COMMITTED ZONE                               │
│                                                                  │
│  🔒 close_breaker (PIVOT) → verify_load → update_scada          │
│                                                                  │
│  Power flowing - forward recovery only                           │
└─────────────────────────────────────────────────────────────────┘
```

## Forward Recovery

If load verification fails after breaker close:
- **RETRY**: Load shedding and balanced redistribution
- Never simply "open breaker" - could cause arc flash or cascade failures

## Running the Example

```bash
cd examples/energy/power_grid
python main.py
```

## Key Features Demonstrated

- `@action("close_breaker", pivot=True)` - Marks energization as irreversible
- `@forward_recovery("verify_load")` - Handles load issues after power flows
- Physical action that cannot be trivially undone

## Business Context

In power grid operations:
- Switching orders are safety-critical documents
- Operators must be notified before any switching
- Isolation must be verified before work begins
- Closing breakers energizes equipment and personnel safety zones
- SCADA systems must reflect actual grid state
