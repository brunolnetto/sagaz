"""A saga: steps that each know how to undo themselves."""

import asyncio

from sagaz import Saga, SagaFailedError, action, compensate


class OrderSaga(Saga):
    saga_name = "order"

    @action("reserve_stock")
    async def reserve_stock(self, ctx):
        print("reserving stock for", ctx["order_id"])
        return {"reservation": "r-1"}  # merged into the context

    @compensate("reserve_stock")
    async def release_stock(self, ctx):
        print("releasing", ctx["reservation"])

    @action("charge", depends_on=["reserve_stock"])
    async def charge(self, ctx):
        if ctx["amount"] > 100:
            raise ValueError("card declined")
        print("charging", ctx["amount"])
        return {"payment": "p-1"}

    @compensate("charge")
    async def refund(self, ctx):
        print("refunding", ctx["payment"])


async def main():
    result = await OrderSaga().run({"order_id": "o-1", "amount": 40})
    print("done:", result["reservation"], result["payment"])

    print("--- an order that fails ---")
    try:
        await OrderSaga().run({"order_id": "o-2", "amount": 500})
    except SagaFailedError as failure:
        print("failed at", failure.failed_step, "->", failure.status.value)


asyncio.run(main())
