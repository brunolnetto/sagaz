# Retail Replenishment Saga

Vendor-managed inventory with EDI documents (855, 856, 810); dispatching the truck is the pivot.

## Workflow

```
forecast_demand → reserve_stock ‖ acknowledge_po → book_carrier → send_ship_notice → 🔒 dispatch_truck → invoice_retailer
```

`‖` marks steps that run in parallel; 🔒 is the pivot (`pivot=True`). Steps before the pivot
have compensations and are undone if a later step fails; once the pivot completes, its
ancestors are tainted and the saga only moves forward.

## Run it

```bash
python -m sagaz.examples.consumer_goods.distribution.retail_replenishment.main
# or
sagaz examples run consumer_goods/distribution/retail_replenishment
```

The demo runs the saga once to completion and once with a simulated failure
(`no_carrier=True`) to show the compensation.
