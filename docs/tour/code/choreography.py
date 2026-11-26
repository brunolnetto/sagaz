"""Choreography: services react to each other's events; nobody is in charge."""

import asyncio

from sagaz.choreography import ChoreographedSaga, ChoreographyEngine, Event, EventBus, on_event


class Orders(ChoreographedSaga):
    @on_event("order.shipped")
    async def confirm(self, event: Event):
        print("orders: order", event.data["order_id"], "is on its way")


class Inventory(ChoreographedSaga):
    @on_event("order.created")
    async def reserve(self, event: Event):
        print("inventory: reserving", event.data["sku"])
        await self.emit("stock.reserved", event.data)


class Shipping(ChoreographedSaga):
    @on_event("stock.reserved")
    async def ship(self, event: Event):
        print("shipping: sending", event.data["sku"])
        await self.emit("order.shipped", event.data)


async def main():
    bus = EventBus()  # in process; Kafka, RabbitMQ and Redis buses work the same way
    engine = ChoreographyEngine(bus, completion_events={"order.shipped"})
    orders = Orders(name="orders")
    for participant in (orders, Inventory(name="inventory"), Shipping(name="shipping")):
        engine.register(participant)
    await engine.start()

    await orders.begin("order.created", {"order_id": "o-1", "sku": "book"})

    await engine.stop()


asyncio.run(main())
