# Subscription Box Saga

One cycle of a direct-to-consumer subscription; the carrier taking the parcel is the pivot.

## Workflow

```
check_subscription → reserve_box_items ‖ charge_subscriber → pick_and_pack → 🔒 hand_to_carrier → send_tracking
```

`‖` marks steps that run in parallel; 🔒 is the pivot (`pivot=True`). Steps before the pivot
have compensations and are undone if a later step fails; once the pivot completes, its
ancestors are tainted and the saga only moves forward.

## Run it

```bash
python -m sagaz.examples.consumer_goods.direct_to_consumer.subscription_box.main
# or
sagaz examples run consumer_goods/direct_to_consumer/subscription_box
```

The demo runs the saga once to completion and once with a simulated failure
(`missing_item="trail-mix"`) to show the compensation.
