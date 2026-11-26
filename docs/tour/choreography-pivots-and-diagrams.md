# Pivots and diagrams

## A point of no return across services

A payment cannot be taken back in a choreography either. Mark its handler `pivot=True`:
once it completes, a later failure no longer undoes what led to it.

This example also uses the form without classes: `participant.on(event_type, handler,
compensation)`, where a handler is a function of the event and the participant.

```python title="choreography_pivot.py"
--8<-- "docs/tour/code/choreography_pivot.py"
```

It prints:

```text
--8<-- "docs/tour/code/choreography_pivot.out"
```

What to notice:

- **Shipping fails after the payment,** so the transaction cannot be rolled back. The
  stock stays reserved: releasing it would contradict a payment that stands.
- **The transaction ends `partially_committed`,** the same status an orchestrated saga
  reports. Someone must act on it.
- **Each participant decides alone what to keep,** from the event's *lineage*: the list
  of actions an event descends from, which travels with every event.

## A diagram of the choreography

Nobody holds the whole picture of a choreography, so sagaz draws it from what the
participants declare: the events they handle and, with `emits=`, the ones they publish.

```python title="choreography_diagram.py"
--8<-- "docs/tour/code/choreography_diagram.py"
```

It prints a [Mermaid](https://mermaid.js.org) flowchart, shown here as rendered:

```mermaid
--8<-- "docs/tour/code/choreography_diagram.out"
```

The thick arrow is the pivot; the dashed one, what a request to compensate undoes.

## Next

- [Pivots in a choreography](../patterns/choreography.md#pivots): what is kept, exactly, and what to watch when upgrading services.
- [Examples](../examples/index.md): complete scenarios.
