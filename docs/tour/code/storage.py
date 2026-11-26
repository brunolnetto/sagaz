"""With a storage, a saga's state survives the process."""

import asyncio
import tempfile
from pathlib import Path

from sagaz import Saga, SagaConfig, SagaFailedError, action, compensate
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage


def order_saga(storage):
    class OrderSaga(Saga):
        saga_name = "order"

        @action("reserve")
        async def reserve(self, ctx):
            return {"reservation": "r-1"}

        @compensate("reserve")
        async def release(self, ctx): ...

        @action("charge", depends_on=["reserve"], max_retries=0)
        async def charge(self, ctx):
            if ctx["amount"] > 100:
                raise ValueError("card declined")

    return OrderSaga(config=SagaConfig(storage=storage, metrics=False, logging=False))


async def main():
    with tempfile.TemporaryDirectory() as folder:
        storage = SQLiteSagaStorage(str(Path(folder) / "sagas.db"))
        await order_saga(storage).run({"amount": 40}, saga_id="order-1")
        try:
            await order_saga(storage).run({"amount": 500}, saga_id="order-2")
        except SagaFailedError:
            pass

        for saga_id in ("order-1", "order-2"):
            state = await storage.load_saga_state(saga_id)
            steps = {step["name"]: step["status"] for step in state["steps"]}
            print(saga_id, state["status"], steps)
        await storage.close()


asyncio.run(main())
