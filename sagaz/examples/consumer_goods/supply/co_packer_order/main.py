"""
Co-Packer Order Saga Example (Consumer Goods)

Many brands make their products at a contract manufacturer (a co-packer). The
brand reserves its raw materials, books a run at the co-packer, sends the
materials over and approves a first-article sample. If the sample is rejected,
the materials come back, the run is cancelled and the reservation released.

Pivot Step: start_production_run
    Once the run starts, the materials are consumed; what follows is
    receiving the finished goods.

Run it:
    python -m sagaz.examples.consumer_goods.supply.co_packer_order.main
"""

import asyncio
import logging
import uuid
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.core.exceptions import SagaFailedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class CoPackerOrderSaga(Saga):
    """Reserve materials, book the run, transfer, approve a sample, produce."""

    saga_name = "co-packer-order"

    @action("reserve_raw_materials")
    async def reserve_raw_materials(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🌾 [{ctx.get('order_id')}] Reserving {ctx.get('materials')}...")
        await asyncio.sleep(0.1)
        return {"material_lot": f"LOT-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("reserve_raw_materials")
    async def release_raw_materials(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Releasing {ctx.get('material_lot')}")
        await asyncio.sleep(0.05)

    @action("book_co_packer_run")
    async def book_co_packer_run(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🗓️ [{ctx.get('order_id')}] Booking a run at {ctx.get('co_packer')}...")
        await asyncio.sleep(0.1)
        return {"run_slot": f"RUN-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("book_co_packer_run")
    async def cancel_co_packer_run(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Cancelling {ctx.get('run_slot')}")
        await asyncio.sleep(0.05)

    @action("transfer_materials", depends_on=["reserve_raw_materials", "book_co_packer_run"])
    async def transfer_materials(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🚚 [{ctx.get('order_id')}] Shipping {ctx.get('material_lot')} over")
        await asyncio.sleep(0.1)
        return {"transfer": f"TRF-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("transfer_materials")
    async def recall_materials(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('order_id')}] Bringing {ctx.get('material_lot')} back")
        await asyncio.sleep(0.05)

    @action("approve_first_article", depends_on=["transfer_materials"])
    async def approve_first_article(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🧪 [{ctx.get('order_id')}] Checking the first-article sample...")
        await asyncio.sleep(0.1)
        if ctx.get("sample_rejected"):
            msg = "the sample's fill weight is out of tolerance"
            raise RuntimeError(msg)
        return {"sample_approved": True}

    @action("start_production_run", depends_on=["approve_first_article"], pivot=True)
    async def start_production_run(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT: the run consumes the materials."""
        logger.info(f"🔒 [{ctx.get('order_id')}] PIVOT: {ctx.get('run_slot')} is running")
        await asyncio.sleep(0.1)
        return {"cases_produced": ctx.get("cases", 0)}

    @action("receive_finished_goods", depends_on=["start_production_run"])
    async def receive_finished_goods(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🏬 [{ctx.get('order_id')}] Receiving {ctx.get('cases_produced')} cases")
        await asyncio.sleep(0.05)
        return {"received": True}


async def main() -> None:
    order = {
        "order_id": "CPO-7731",
        "co_packer": "PACKCO-SP",
        "materials": ["oats", "honey", "film-roll"],
        "cases": 4_000,
    }
    logger.info("=== A run that produces ===")
    await CoPackerOrderSaga().run(dict(order))

    logger.info("=== The sample is rejected: materials return, run cancelled ===")
    try:
        await CoPackerOrderSaga().run({**order, "sample_rejected": True})
    except SagaFailedError as e:
        logger.info(f"Order rolled back: {e}")


if __name__ == "__main__":
    asyncio.run(main())
