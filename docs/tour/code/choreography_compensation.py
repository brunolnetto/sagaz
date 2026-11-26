"""When a participant fails, the others undo what they did in that transaction."""

import asyncio
import logging

from sagaz.choreography import (
    ChoreographedSaga,
    ChoreographyEngine,
    ChoreographyTracker,
    Event,
    EventBus,
    compensate,
    on_event,
)

logging.disable(logging.ERROR)  # the engine logs the failure; the example prints its own


class Inventory(ChoreographedSaga):
    @on_event("order.created")
    async def reserve(self, event: Event):
        print("inventory: reserving", event.data["sku"])
        await self.emit("stock.reserved", event.data)

    @compensate("order.created")
    async def release(self, event: Event):
        print("inventory: releasing", event.data["sku"])


class Payments(ChoreographedSaga):
    @on_event("stock.reserved", max_retries=0)
    async def charge(self, event: Event):
        if event.data["amount"] > 100:
            raise ValueError("card declined")
        print("payments: charging", event.data["amount"])
        await self.emit("order.paid", event.data)


async def main():
    bus = EventBus()
    engine = ChoreographyEngine(bus, completion_events={"order.paid"})
    tracker = ChoreographyTracker(bus, completion_events={"order.paid"})  # sees every event
    orders = ChoreographedSaga(name="orders")
    for participant in (orders, Inventory(name="inventory"), Payments(name="payments")):
        engine.register(participant)
    await engine.start()
    await tracker.start()

    for order_id, amount in (("o-1", 40), ("o-2", 500)):
        await orders.begin(
            "order.created", {"sku": "book", "amount": amount}, correlation_id=order_id
        )
        status = await tracker.status(order_id)
        print(order_id, "->", status.status)

    await tracker.stop()
    await engine.stop()


asyncio.run(main())
