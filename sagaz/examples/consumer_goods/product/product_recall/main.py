"""
Product Recall Saga Example (Consumer Goods)

A suspected defect puts the affected batches on hold while a lab confirms it.
If the lab clears the product, the holds are released. Once the recall is filed
with the regulator, it is public and binding, and the saga only moves forward.

Pivot Step: file_with_regulator
    A filed recall cannot be withdrawn. Its ancestors (the production halt and
    the quarantine) become tainted: they stay in place even if a later step
    fails, which is exactly what a recall needs.

Run it:
    python -m sagaz.examples.consumer_goods.product.product_recall.main
"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.core.exceptions import SagaFailedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class ProductRecallSaga(Saga):
    """Hold the batches, confirm the defect, file the recall, pull and refund."""

    saga_name = "product-recall"

    @action("identify_batches")
    async def identify_batches(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🔎 [{ctx.get('recall_id')}] Tracing batches with lot {ctx.get('lot')}...")
        await asyncio.sleep(0.1)
        return {"batches": [f"{ctx.get('lot')}-{n:02d}" for n in range(1, 4)]}

    @action("halt_production", depends_on=["identify_batches"])
    async def halt_production(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"⛔ [{ctx.get('recall_id')}] Halting lines that produced the lot...")
        await asyncio.sleep(0.1)
        return {"halted_lines": ["LINE-3"]}

    @compensate("halt_production")
    async def resume_production(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('recall_id')}] Resuming {ctx.get('halted_lines')}")
        await asyncio.sleep(0.05)

    @action("quarantine_stock", depends_on=["identify_batches"])
    async def quarantine_stock(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🔐 [{ctx.get('recall_id')}] Quarantining {ctx.get('batches')} in warehouses")
        await asyncio.sleep(0.1)
        return {"quarantined_units": 18_400}

    @compensate("quarantine_stock")
    async def release_quarantine(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('recall_id')}] Releasing the quarantined stock")
        await asyncio.sleep(0.05)

    @action("confirm_defect", depends_on=["halt_production", "quarantine_stock"])
    async def confirm_defect(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🧪 [{ctx.get('recall_id')}] Waiting for the lab result...")
        await asyncio.sleep(0.15)
        if not ctx.get("defect_confirmed", True):
            msg = "lab cleared the lot: no recall"
            raise RuntimeError(msg)
        return {"lab_report": f"LAB-{ctx.get('lot')}"}

    @action("file_with_regulator", depends_on=["confirm_defect"], pivot=True)
    async def file_with_regulator(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT: the recall is filed and public."""
        logger.info(f"🔒 [{ctx.get('recall_id')}] PIVOT: filing the recall with the regulator...")
        await asyncio.sleep(0.1)
        return {"filing_id": f"FIL-{ctx.get('recall_id')}"}

    @action("instruct_retailers", depends_on=["file_with_regulator"])
    async def instruct_retailers(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🏪 [{ctx.get('recall_id')}] Telling retailers to pull the lot from shelves")
        await asyncio.sleep(0.1)
        return {"retailers_notified": 214}

    @action("open_refunds", depends_on=["file_with_regulator"])
    async def open_refunds(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"💸 [{ctx.get('recall_id')}] Opening the consumer refund program")
        await asyncio.sleep(0.1)
        return {"refund_program": f"RFND-{ctx.get('recall_id')}"}


async def main() -> None:
    logger.info("=== Defect confirmed: the recall goes ahead ===")
    await ProductRecallSaga().run({"recall_id": "RC-0091", "lot": "L2611"})

    logger.info("=== The lab clears the lot: the holds are released ===")
    try:
        await ProductRecallSaga().run(
            {"recall_id": "RC-0092", "lot": "L2612", "defect_confirmed": False}
        )
    except SagaFailedError as e:
        logger.info(f"No recall: {e}")


if __name__ == "__main__":
    asyncio.run(main())
