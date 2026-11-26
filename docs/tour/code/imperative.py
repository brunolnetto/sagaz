"""The same saga without a class: steps added one by one."""

import asyncio

from sagaz import Saga


async def reserve(ctx):
    print("reserving", ctx["sku"])
    return {"reservation": "r-1"}


async def release(ctx):
    print("releasing", ctx["reservation"])


async def charge(ctx):
    print("charging", ctx["amount"])


async def main():
    saga = Saga(name="order")
    saga.add_step("reserve", reserve, release)
    saga.add_step("charge", charge, depends_on=["reserve"])
    await saga.run({"sku": "book", "amount": 30})


asyncio.run(main())
