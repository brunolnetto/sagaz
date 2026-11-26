# Tour

What sagaz does, one feature per page. Every page has one small script: copy it, run it
with `python <file>.py`, and you get the output shown under it. The scripts need nothing
but `pip install sagaz`: no database, no broker.

A **saga** is a business transaction made of steps, where each step knows how to undo
itself. If a step fails, the steps already done are undone, in reverse order. sagaz
offers two ways to coordinate the steps.

## Orchestrated sagas

One object, the saga, knows every step and runs them.

| Page | You will see |
|---|---|
| [Your first saga](first-saga.md) | Steps, compensations, and what happens when a step fails |
| [Parallel steps](parallel-steps.md) | Steps that run at the same time, and steps that wait for others |
| [Retries, timeouts and deadlines](retries-timeouts-deadlines.md) | A flaky step retried, a slow saga stopped |
| [Running once](run-once.md) | A repeated request that does not charge twice |
| [Points of no return](pivots.md) | A step that cannot be undone, and recovering forward after it |
| [Listeners](listeners.md) | Logging, metrics and auditing without touching the steps |
| [Storage](storage.md) | A saga's state kept in a database |

## Choreographed sagas

No one is in charge: each service reacts to the others' events.

| Page | You will see |
|---|---|
| [Your first choreography](choreography.md) | Participants, events, and undoing a transaction across services |
| [Pivots and diagrams](choreography-pivots-and-diagrams.md) | A point of no return across services, and a picture of who talks to whom |

Not sure which one you need? Start with an orchestrated saga: it is simpler to read and
to debug. Choose a choreography when the steps belong to different services that should
not know about each other. [Orchestration or choreography?](../patterns/choreography.md#orchestration-or-choreography)
compares them.

When you want a complete scenario instead of one feature, go to the
[examples](../examples/index.md).
