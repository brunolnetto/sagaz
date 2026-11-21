# Returns Processing Saga

A consumer return: authorize, receive, inspect, restock or write off, refund; the refund is the pivot.

## Workflow

```
authorize_return → receive_parcel → inspect_item → adjust_inventory → 🔒 issue_refund → close_return
```

`‖` marks steps that run in parallel; 🔒 is the pivot (`pivot=True`). Steps before the pivot
have compensations and are undone if a later step fails; once the pivot completes, its
ancestors are tainted and the saga only moves forward.

## Run it

```bash
python -m sagaz.examples.consumer_goods.direct_to_consumer.returns_processing.main
# or
sagaz examples run consumer_goods/direct_to_consumer/returns_processing
```

The demo runs the saga once to completion and once with a simulated failure
(`condition="not_ours"`) to show the compensation.
