# Product Launch Saga

Launch a product line: production capacity, packaging, shelf space, carriers and a campaign; shipping the first wave is the pivot.

## Workflow

```
reserve_production_capacity → order_packaging ‖ allocate_shelf_space → book_distribution ‖ schedule_campaign → 🔒 ship_to_retailers → announce_launch
```

`‖` marks steps that run in parallel; 🔒 is the pivot (`pivot=True`). Steps before the pivot
have compensations and are undone if a later step fails; once the pivot completes, its
ancestors are tainted and the saga only moves forward.

## Run it

```bash
python -m sagaz.examples.consumer_goods.product.product_launch.main
# or
sagaz examples run consumer_goods/product/product_launch
```

The demo runs the saga once to completion and once with a simulated failure
(`fail_at="book_distribution"`) to show the compensation.
