# Product Recall Saga

Hold the affected batches while a lab confirms a defect; filing with the regulator is the pivot, and taints the production halt and the quarantine so they stay in place.

## Workflow

```
identify_batches → halt_production ‖ quarantine_stock → confirm_defect → 🔒 file_with_regulator → instruct_retailers ‖ open_refunds
```

`‖` marks steps that run in parallel; 🔒 is the pivot (`pivot=True`). Steps before the pivot
have compensations and are undone if a later step fails; once the pivot completes, its
ancestors are tainted and the saga only moves forward.

## Run it

```bash
python -m sagaz.examples.consumer_goods.product.product_recall.main
# or
sagaz examples run consumer_goods/product/product_recall
```

The demo runs the saga once to completion and once with a simulated failure
(`defect_confirmed=False`) to show the compensation.
