"""A pivot is a point of no return; after it, the saga recovers forward."""

import asyncio

from sagaz import RecoveryAction, Saga, SagaFailedError, action, compensate, forward_recovery


class OrderSaga(Saga):
    saga_name = "order"

    @action("reserve")
    async def reserve(self, ctx):
        print("stock reserved")

    @compensate("reserve")
    async def release(self, ctx):
        print("stock released")

    @action("charge", depends_on=["reserve"], pivot=True)  # cannot be undone
    async def charge(self, ctx):
        print("card charged")

    @action("ship", depends_on=["charge"], max_retries=0)
    async def ship(self, ctx):
        if ctx["carrier"] == "fast":
            raise RuntimeError("carrier unavailable")
        print("shipped with", ctx["carrier"])

    @forward_recovery("ship")
    async def recover_shipping(self, ctx, error):
        if ctx["carrier"] == "fast" and ctx.get("backup"):
            ctx["carrier"] = ctx["backup"]  # the retried step reads it
            return RecoveryAction.RETRY_WITH_ALTERNATE
        return RecoveryAction.MANUAL_INTERVENTION


async def main():
    await OrderSaga().run({"carrier": "fast", "backup": "slow"})

    print("--- with no backup carrier ---")
    try:
        await OrderSaga().run({"carrier": "fast"})
    except SagaFailedError as failure:
        print("stopped at", failure.failed_step, "->", failure.status.value)


asyncio.run(main())
