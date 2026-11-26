# Parallel steps

Booking a flight and a hotel do not depend on each other, so there is no reason to do
one after the other. Steps without `depends_on` run at the same time. A step that names
others in `depends_on` waits for all of them.

```python title="parallel.py"
--8<-- "docs/tour/code/parallel.py"
```

It prints:

```text
--8<-- "docs/tour/code/parallel.out"
```

What to notice:

- **The dependencies are the whole plan.** sagaz builds the order from them: no
  dependency means "as soon as possible".
- **`send_itinerary` sees both results** in its context, because it waited for both steps.
- **Compensation follows the dependencies backwards.** If `send_itinerary` failed, both
  bookings would be undone.

## When a parallel step fails

By default the other steps running at that moment get 2 seconds to finish, and those
still running are then cancelled. You can instead wait for all of them, or cancel at
once: see [parallel failure strategies](../guides/configuration.md).

## Next

- [Retries, timeouts and deadlines](retries-timeouts-deadlines.md).
