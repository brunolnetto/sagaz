# Chemical Reactor Saga

This example demonstrates a **reaction initiation pivot point** in chemical manufacturing. Once reagents are combined and the reaction starts, it cannot be stopped - only controlled.

## Pivot Point

**Step:** `initiate_reaction`

Once the reaction is initiated:
- Reagents are combined and reacting
- The reaction may be exothermic (releasing heat)
- Cannot separate reagents once mixed
- Must control the reaction to completion

## Saga Steps

```
┌─────────────────────────────────────────────────────────────────┐
│                     REVERSIBLE ZONE                              │
├─────────────────────────────────────────────────────────────────┤
│  validate_recipe → load_reagents → preheat_reactor              │
│                                                                  │
│  Can abort and recover reagents before mixing                   │
├─────────────────────────────────────────────────────────────────┤
│                    ↓ PIVOT BOUNDARY ↓                            │
├─────────────────────────────────────────────────────────────────┤
│                     COMMITTED ZONE                               │
│                                                                  │
│  🔒 initiate_reaction (PIVOT) → monitor → quench → quality      │
│                                                                  │
│  Reaction in progress - forward recovery only                    │
└─────────────────────────────────────────────────────────────────┘
```

## Forward Recovery

If reaction monitoring detects anomalies:
- **RETRY**: Adjust temperature/pressure, emergency cooling
- Never stop a reaction mid-way - could be dangerous

## Running the Example

```bash
cd examples/manufacturing/chemical_reactor
python main.py
```

## Key Features Demonstrated

- `@action("initiate_reaction", pivot=True)` - Marks reaction start as irreversible
- `@forward_recovery("monitor_reaction")` - Handles anomalies with emergency procedures
- Physical/chemical transformation that cannot be undone

## Business Context

In chemical manufacturing:
- Recipes must be validated before mixing
- Reagents are expensive and must be handled carefully
- Reactor preheating ensures proper reaction conditions
- Once initiated, reactions must be seen through
- Quality analysis determines if batch meets specifications
- Failed batches may need to be disposed as hazardous waste
