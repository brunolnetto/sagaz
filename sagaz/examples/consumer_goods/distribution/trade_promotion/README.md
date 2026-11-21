# Trade Promotion Saga

A temporary price reduction funded by the brand; activating the promotion in stores is the pivot.

## Workflow

```
approve_budget → agree_terms → update_price_list ‖ schedule_uplift_production → 🔒 activate_promotion → settle_deductions
```

`‖` marks steps that run in parallel; 🔒 is the pivot (`pivot=True`). Steps before the pivot
have compensations and are undone if a later step fails; once the pivot completes, its
ancestors are tainted and the saga only moves forward.

## Run it

```bash
python -m sagaz.examples.consumer_goods.distribution.trade_promotion.main
# or
sagaz examples run consumer_goods/distribution/trade_promotion
```

The demo runs the saga once to completion and once with a simulated failure
(`line_down=True`) to show the compensation.
