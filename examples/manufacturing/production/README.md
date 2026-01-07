# Manufacturing Production Saga

**Category:** Manufacturing/Industrial  
**Pivot Type:** Physical Action

## Description

This saga demonstrates a manufacturing production workflow where starting the production run is the **point of no return**. Once CNC machines start cutting and materials are being transformed, the operation cannot be reversed without creating scrap.

## Saga Flow

```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ validate_order    │ ──→ │reserve_materials│ ──→ │ schedule_production │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
┌─────────────────────────────┐     ┌───────────────────────┐     ┌───────────────┐
│ start_production            │ ──→ │ quality_check         │ ──→ │ package_ship  │
│ 🔒 PIVOT (machines running, │     │ (forward only)        │     │ (forward only)│
│   materials in process)     │     │                       │     │               │
└─────────────────────────────┘     └───────────────────────┘     └───────────────┘
```

## Pivot Step: `start_production`

Once the production run begins:

### Why It's Irreversible

- CNC machines are physically cutting/shaping raw materials
- Steel is being machined - cannot be "un-cut"
- Stopping mid-production creates partial (scrap) parts
- Materials are consumed in the transformation process

### What Happens After Pivot

- Must complete the production run
- Quality failures require rework or scrap decision
- Forward recovery strategies apply

## Forward Recovery Strategies

| Scenario | Strategy | Action |
|----------|----------|--------|
| Minor quality defect | RETRY | Rework (grinding, polishing) |
| Material flaw | RETRY_WITH_ALTERNATE | Use secondary materials |
| Critical failure | MANUAL_INTERVENTION | Supervisor scrap decision |

## Usage

```python
from examples.manufacturing.production import ManufacturingProductionSaga

saga = ManufacturingProductionSaga()

result = await saga.run({
    "work_order_id": "WO-2026-001",
    "product_sku": "WIDGET-PRO-X1",
    "quantity": 10,
    "materials": [
        {"sku": "STEEL-304", "quantity": 5, "lot": "LOT-A1"},
        {"sku": "BEARING-6205", "quantity": 10, "lot": "LOT-B2"},
    ],
    "machine_id": "CNC-MILL-01",
    "operator_id": "OP-123",
    "quality_specs": {"tolerance_mm": 0.05},
})
```

## Context Schema

| Field | Type | Description |
|-------|------|-------------|
| `work_order_id` | str | Production work order ID |
| `product_sku` | str | SKU of product to manufacture |
| `quantity` | int | Number of units to produce |
| `materials` | list[dict] | Materials [{sku, quantity, lot}] |
| `machine_id` | str | CNC machine identifier |
| `operator_id` | str | Operator running the job |
| `quality_specs` | dict | Quality specifications |

## Running the Example

```bash
python examples/manufacturing/production/main.py
```

## Key Concepts Demonstrated

1. **Physical Irreversibility**: Materials are physically transformed
2. **MES Integration**: Manufacturing Execution System patterns
3. **Quality Gates**: Post-production quality inspection
4. **Rework vs Scrap**: Forward recovery decision making
