# Packaging Switch Saga

Moving a SKU to a new packaging supplier with label validation (allergens, nutrition panel, barcode); cutting the line over is the pivot.

## Workflow

```
qualify_supplier → validate_label → update_bill_of_materials ‖ place_first_order → 🔒 cut_over_line → retire_old_supplier
```

`‖` marks steps that run in parallel; 🔒 is the pivot (`pivot=True`). Steps before the pivot
have compensations and are undone if a later step fails; once the pivot completes, its
ancestors are tainted and the saga only moves forward.

## Run it

```bash
python -m sagaz.examples.consumer_goods.supply.packaging_switch.main
# or
sagaz examples run consumer_goods/supply/packaging_switch
```

The demo runs the saga once to completion and once with a simulated failure
(a label without the allergen statement) to show the compensation.
