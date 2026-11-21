"""
Packaging Switch Saga Example (Consumer Goods)

Moving a product to a new packaging supplier: qualify the supplier, validate
the new label artwork against labeling rules (allergens, nutrition panel,
barcode), update the bill of materials and place a first order. If anything
fails before the line switches over, the change is unwound.

Pivot Step: cut_over_line
    Once the production line runs on the new packaging, the old stock is
    written off and the switch is done.

Run it:
    python -m sagaz.examples.consumer_goods.supply.packaging_switch.main
"""

import asyncio
import logging
import uuid
from typing import Any

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REQUIRED_LABEL_FIELDS = ("allergens", "nutrition_panel", "barcode")


class PackagingSwitchSaga(Saga):
    """Qualify, validate the label, update the BOM, order, cut over."""

    saga_name = "packaging-switch"

    @action("qualify_supplier")
    async def qualify_supplier(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🏷️ [{ctx.get('sku')}] Qualifying {ctx.get('new_supplier')}...")
        await asyncio.sleep(0.1)
        return {"supplier_qualified": True}

    @compensate("qualify_supplier")
    async def withdraw_qualification(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('sku')}] Withdrawing {ctx.get('new_supplier')}'s status")
        await asyncio.sleep(0.05)

    @action("validate_label", depends_on=["qualify_supplier"])
    async def validate_label(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🔎 [{ctx.get('sku')}] Validating the new label artwork...")
        await asyncio.sleep(0.1)
        artwork = ctx.get("artwork", {})
        missing = [field for field in REQUIRED_LABEL_FIELDS if not artwork.get(field)]
        if missing:
            msg = f"the label is missing {', '.join(missing)}"
            raise RuntimeError(msg)
        return {"artwork_version": artwork.get("version")}

    @action("update_bill_of_materials", depends_on=["validate_label"])
    async def update_bill_of_materials(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"📋 [{ctx.get('sku')}] Pointing the BOM to the new packaging")
        await asyncio.sleep(0.05)
        return {"bom_revision": "B"}

    @compensate("update_bill_of_materials")
    async def restore_bill_of_materials(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('sku')}] Restoring BOM revision A")
        await asyncio.sleep(0.05)

    @action("place_first_order", depends_on=["validate_label"])
    async def place_first_order(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🧾 [{ctx.get('sku')}] Ordering the first lot of packaging")
        await asyncio.sleep(0.05)
        return {"packaging_po": f"PO-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("place_first_order")
    async def cancel_first_order(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('sku')}] Cancelling {ctx.get('packaging_po')}")
        await asyncio.sleep(0.05)

    @action(
        "cut_over_line", depends_on=["update_bill_of_materials", "place_first_order"], pivot=True
    )
    async def cut_over_line(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT: the line runs on the new packaging."""
        logger.info(f"🔒 [{ctx.get('sku')}] PIVOT: line switched; old packaging written off")
        await asyncio.sleep(0.1)
        return {"cut_over": True}

    @action("retire_old_supplier", depends_on=["cut_over_line"])
    async def retire_old_supplier(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"👋 [{ctx.get('sku')}] Retiring {ctx.get('old_supplier')} for this SKU")
        await asyncio.sleep(0.05)
        return {"old_supplier_retired": True}


async def main() -> None:
    change = {
        "sku": "SKU-CEREAL-500",
        "old_supplier": "BOXWORKS",
        "new_supplier": "GREENPACK",
        "artwork": {"version": "v7", "allergens": True, "nutrition_panel": True, "barcode": True},
    }
    logger.info("=== A switch that goes through ===")
    await PackagingSwitchSaga().run(dict(change))

    logger.info("=== The label misses the allergen statement: the supplier is withdrawn ===")
    try:
        await PackagingSwitchSaga().run(
            {**change, "artwork": {**change["artwork"], "allergens": False}}
        )
    except RuntimeError as e:
        logger.info(f"Switch rolled back: {e}")


if __name__ == "__main__":
    asyncio.run(main())
