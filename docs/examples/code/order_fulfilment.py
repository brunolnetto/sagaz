"""Order fulfilment as a choreography of four services.

    orders ──order.created──▶ inventory ──stock.reserved──▶ payments ──payment.captured──▶ shipping
                                                                                              │
    orders ◀────────────────────────────── order.shipped ◀────────────────────────────────────┘

Three orders show the three ways a transaction can end:

- o-1 completes;
- o-2 fails at the payment, before the point of no return: everything is undone;
- o-3 fails at shipping, after the payment was captured: what led to the payment stays.

The participants keep their state in SQLite, as separate services sharing a database
would; a tracker tells each transaction's status, and a listener counts the outcomes.
"""

import asyncio
import logging
import tempfile
from collections import Counter
from pathlib import Path

from sagaz import SagaListener
from sagaz.choreography import (
    ChoreographedSaga,
    ChoreographyEngine,
    ChoreographyTracker,
    Event,
    EventBus,
    compensate,
    on_event,
)
from sagaz.choreography.state.sqlite import SQLiteParticipantState

logging.disable(logging.ERROR)  # the engine logs each failure; this example prints its own

COMPLETION = {"order.shipped"}


class Inventory(ChoreographedSaga):
    """Reserves stock, and releases it if the transaction is undone."""

    def __init__(self) -> None:
        super().__init__(name="inventory")
        self.stock = {"book": 5, "lamp": 1}

    @on_event("order.created", emits=["stock.reserved"])
    async def reserve(self, event: Event) -> None:
        sku = event.data["sku"]
        if self.stock[sku] < 1:
            raise RuntimeError(f"{sku} is out of stock")
        self.stock[sku] -= 1
        await self.emit("stock.reserved", event.data)

    @compensate("order.created")
    async def release(self, event: Event) -> None:
        self.stock[event.data["sku"]] += 1
        print(f"  inventory: released the {event.data['sku']} of {event.saga_id}")


class Payments(ChoreographedSaga):
    """Captures the payment: the point of no return of an order."""

    def __init__(self) -> None:
        super().__init__(name="payments")
        self.captured: dict[str, float] = {}

    @on_event("stock.reserved", pivot=True, max_retries=0, emits=["payment.captured"])
    async def capture(self, event: Event) -> None:
        if event.data["amount"] > 100:
            raise ValueError("card declined")
        self.captured[event.saga_id or ""] = event.data["amount"]
        await self.emit("payment.captured", event.data)


class Shipping(ChoreographedSaga):
    """Hands the parcel to a carrier."""

    def __init__(self) -> None:
        super().__init__(name="shipping")

    @on_event("payment.captured", max_retries=1, emits=["order.shipped"])
    async def ship(self, event: Event) -> None:
        if event.data["address"] == "unknown":
            raise RuntimeError("no carrier serves this address")
        await self.emit("order.shipped", event.data)


class Outcomes(SagaListener):
    """Counts how transactions end. A tracker's listeners see whole transactions."""

    def __init__(self) -> None:
        self.count: Counter[str] = Counter()

    async def on_saga_complete(self, saga_name, saga_id, ctx) -> None:
        self.count["completed"] += 1

    async def on_saga_failed(self, saga_name, saga_id, ctx, error) -> None:
        self.count[ctx["status"]] += 1


ORDERS = [
    ("o-1", {"sku": "book", "amount": 30.0, "address": "12 Main St"}),
    ("o-2", {"sku": "book", "amount": 900.0, "address": "12 Main St"}),
    ("o-3", {"sku": "lamp", "amount": 45.0, "address": "unknown"}),
]


async def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        bus = EventBus()
        state = SQLiteParticipantState(str(Path(folder) / "participants.db"))
        engine = ChoreographyEngine(
            bus, completion_events=COMPLETION, state=state, retry_backoff_base=0
        )
        outcomes = Outcomes()
        tracker = ChoreographyTracker(bus, completion_events=COMPLETION, listeners=[outcomes])
        orders = ChoreographedSaga(name="orders")
        inventory, payments = Inventory(), Payments()
        for participant in (orders, inventory, payments, Shipping()):
            engine.register(participant)
        await engine.start()
        await tracker.start()

        for order_id, order in ORDERS:
            print(f"{order_id}: {order['sku']} for {order['amount']:.2f} to {order['address']}")
            await orders.begin("order.created", order, correlation_id=order_id)
            status = await tracker.status(order_id)
            print(f"  -> {status.status}")
            if status.failure:
                print(f"  failed at {status.failure['participant']}: {status.failure['reason']}")
            for participant, report in sorted(status.compensated_by.items()):
                if report.get("kept"):
                    print(f"  {participant} kept {report['kept']}: a pivot followed it")

        print()
        print("stock left:", inventory.stock)
        print("payments captured:", payments.captured)
        print("outcomes:", dict(sorted(outcomes.count.items())))

        await tracker.stop()
        await engine.stop()
        await state.close()


asyncio.run(main())
