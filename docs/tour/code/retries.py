"""A step is retried, bounded by a timeout, and the whole saga by a deadline."""

import asyncio

from sagaz import Saga, SagaFailedError, action

attempts = 0


class PaymentSaga(Saga):
    saga_name = "payment"

    # Up to 3 retries after the first attempt, each attempt limited to 1 second.
    @action("charge", max_retries=3, timeout_seconds=1)
    async def charge(self, ctx):
        global attempts
        attempts += 1
        if attempts < 3:
            print(f"attempt {attempts}: gateway unavailable")
            raise ConnectionError("gateway unavailable")
        print(f"attempt {attempts}: charged")


class ReportSaga(Saga):
    saga_name = "report"

    @action("build")
    async def build(self, ctx):
        await asyncio.sleep(5)  # far too slow


async def main():
    await PaymentSaga().run({})

    print("--- a deadline for the whole saga ---")
    try:
        await ReportSaga().run({}, deadline=0.2)  # seconds
    except SagaFailedError as failure:
        print("stopped by", type(failure.__cause__).__name__, "->", failure.status.value)


asyncio.run(main())
