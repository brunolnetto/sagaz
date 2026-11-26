"""Listeners see every step, without the steps knowing about them."""

import asyncio

from sagaz import Saga, SagaFailedError, SagaListener, action, compensate


class Audit(SagaListener):
    async def on_saga_start(self, saga_name, saga_id, ctx):
        print(f"[audit] {saga_name} started")

    async def on_step_success(self, saga_name, step_name, ctx, result):
        print(f"[audit] {step_name} ok")

    async def on_step_failure(self, saga_name, step_name, ctx, error):
        print(f"[audit] {step_name} failed: {error}")

    async def on_compensation_complete(self, saga_name, step_name, ctx):
        print(f"[audit] {step_name} undone")

    async def on_saga_failed(self, saga_name, saga_id, ctx, error):
        print(f"[audit] {saga_name} ended {error.status.value}")


class OrderSaga(Saga):
    saga_name = "order"
    listeners = [Audit()]

    @action("reserve")
    async def reserve(self, ctx): ...

    @compensate("reserve")
    async def release(self, ctx): ...

    @action("charge", depends_on=["reserve"], max_retries=0)
    async def charge(self, ctx):
        raise ValueError("card declined")


async def main():
    try:
        await OrderSaga().run({})
    except SagaFailedError:
        pass


asyncio.run(main())
