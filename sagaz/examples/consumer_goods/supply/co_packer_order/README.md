# Co-Packer Order Saga

A production order at a contract manufacturer, gated by a first-article sample; starting the run is the pivot.

## Workflow

```
reserve_raw_materials ‖ book_co_packer_run → transfer_materials → approve_first_article → 🔒 start_production_run → receive_finished_goods
```

`‖` marks steps that run in parallel; 🔒 is the pivot (`pivot=True`). Steps before the pivot
have compensations and are undone if a later step fails; once the pivot completes, its
ancestors are tainted and the saga only moves forward.

## Run it

```bash
python -m sagaz.examples.consumer_goods.supply.co_packer_order.main
# or
sagaz examples run consumer_goods/supply/co_packer_order
```

The demo runs the saga once to completion and once with a simulated failure
(`sample_rejected=True`) to show the compensation.
