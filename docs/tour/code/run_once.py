"""A saga id runs once, and a step with a key does its effect once."""

import asyncio

from sagaz import Saga, SagaAlreadyExistsError, action


class ChargeSaga(Saga):
    saga_name = "charge"

    # The key is built from the context: one charge per order, in any saga.
    @action("charge", idempotency_key="charge-{order_id}")
    async def charge(self, ctx):
        print("charging order", ctx["order_id"])
        return {"payment": f"p-{ctx['order_id']}"}


async def main():
    await ChargeSaga().run({"order_id": "o-1"}, saga_id="checkout-1")

    # The same request arrives again (a retry, a double click).
    try:
        await ChargeSaga().run({"order_id": "o-1"}, saga_id="checkout-1")
    except SagaAlreadyExistsError as error:
        print("refused:", error)

    # Another saga for the same order: the step is skipped, its result reused.
    result = await ChargeSaga().run({"order_id": "o-1"}, saga_id="checkout-2")
    print("second saga got", result["payment"], "without charging again")


asyncio.run(main())
