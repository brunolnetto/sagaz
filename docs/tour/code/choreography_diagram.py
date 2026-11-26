"""A diagram of a choreography, from what its participants declare."""

from sagaz.choreography import ChoreographedSaga, ChoreographyEngine, EventBus


async def handler(event, me): ...


engine = ChoreographyEngine(EventBus(), completion_events={"order.shipped"})
for participant in (
    ChoreographedSaga(name="orders"),
    ChoreographedSaga(name="inventory").on(
        "order.created", handler, compensation=handler, emits=["stock.reserved"]
    ),
    ChoreographedSaga(name="payments").on(
        "stock.reserved", handler, pivot=True, emits=["payment.captured"]
    ),
    ChoreographedSaga(name="shipping").on("payment.captured", handler, emits=["order.shipped"]),
):
    engine.register(participant)

print(engine.to_mermaid())
