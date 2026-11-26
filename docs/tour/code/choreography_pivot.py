"""A pivot in a choreography: what led to it is not undone. Written without classes."""

import asyncio
import logging

from sagaz.choreography import ChoreographedSaga, ChoreographyEngine, ChoreographyTracker, EventBus

logging.disable(logging.ERROR)


async def reserve(event, me):
    await me.emit("stock.reserved")


async def release(event, me):
    print("inventory: stock released")


async def charge(event, me):
    print("payments: card charged")
    await me.emit("payment.captured")


async def ship(event, me):
    raise RuntimeError("no carrier")


async def main():
    bus = EventBus()
    engine = ChoreographyEngine(bus, completion_events={"order.shipped"}, default_max_retries=0)
    tracker = ChoreographyTracker(bus, completion_events={"order.shipped"})
    orders = ChoreographedSaga(name="orders")
    participants = [
        orders,
        ChoreographedSaga(name="inventory").on(
            "order.created", reserve, release, emits=["stock.reserved"]
        ),
        # A payment cannot be taken back: what led to it stays done.
        ChoreographedSaga(name="payments").on(
            "stock.reserved", charge, pivot=True, emits=["payment.captured"]
        ),
        ChoreographedSaga(name="shipping").on("payment.captured", ship, emits=["order.shipped"]),
    ]
    for participant in participants:
        engine.register(participant)
    await engine.start()
    await tracker.start()

    await orders.begin("order.created", correlation_id="o-1")
    status = await tracker.status("o-1")
    print("o-1 ->", status.status, "(the stock was not released)")

    await tracker.stop()
    await engine.stop()


asyncio.run(main())
