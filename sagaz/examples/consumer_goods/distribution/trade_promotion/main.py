"""
Trade Promotion Saga Example (Consumer Goods)

A temporary price reduction run with a retailer: the brand funds the discount,
agrees the terms, changes the price list and makes enough product for the
uplift. Until the promotion is live in stores, any failure unwinds the budget,
the agreement, the prices and the extra production run.

Pivot Step: activate_promotion
    Once shelf prices change in stores, the promotion runs to its end date;
    the retailer then claims the funding through deductions.

Run it:
    python -m sagaz.examples.consumer_goods.distribution.trade_promotion.main
"""

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.core.exceptions import SagaFailedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class TradePromotionSaga(Saga):
    """Fund, agree, price, produce, then run a retail promotion."""

    saga_name = "trade-promotion"

    @action("approve_budget")
    async def approve_budget(self, ctx: SagaContext) -> dict[str, Any]:
        funding = Decimal(str(ctx.get("discount_per_unit"))) * ctx.get("expected_units", 0)
        logger.info(f"💰 [{ctx.get('promo_id')}] Committing ${funding:,.2f} of trade spend...")
        await asyncio.sleep(0.1)
        if funding > Decimal(str(ctx.get("budget_left", "1000000"))):
            msg = "not enough trade budget left this quarter"
            raise RuntimeError(msg)
        return {"funding": str(funding)}

    @compensate("approve_budget")
    async def return_budget(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('promo_id')}] Returning ${ctx.get('funding')} to budget")
        await asyncio.sleep(0.05)

    @action("agree_terms", depends_on=["approve_budget"])
    async def agree_terms(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🤝 [{ctx.get('promo_id')}] Signing terms with {ctx.get('retailer')}...")
        await asyncio.sleep(0.1)
        return {"agreement": f"AGR-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("agree_terms")
    async def void_terms(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('promo_id')}] Voiding agreement {ctx.get('agreement')}")
        await asyncio.sleep(0.05)

    @action("update_price_list", depends_on=["agree_terms"])
    async def update_price_list(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"🏷️ [{ctx.get('promo_id')}] Publishing the promotional price list...")
        await asyncio.sleep(0.1)
        return {"price_list_version": 42}

    @compensate("update_price_list")
    async def restore_price_list(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('promo_id')}] Restoring the regular price list")
        await asyncio.sleep(0.05)

    @action("schedule_uplift_production", depends_on=["agree_terms"])
    async def schedule_uplift_production(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(
            f"🏭 [{ctx.get('promo_id')}] Scheduling {ctx.get('expected_units')} extra units"
        )
        await asyncio.sleep(0.1)
        if ctx.get("line_down"):
            msg = "the co-packer's line is down"
            raise RuntimeError(msg)
        return {"production_run": f"RUN-{uuid.uuid4().hex[:6].upper()}"}

    @compensate("schedule_uplift_production")
    async def cancel_uplift_production(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('promo_id')}] Cancelling run {ctx.get('production_run')}")
        await asyncio.sleep(0.05)

    @action(
        "activate_promotion",
        depends_on=["update_price_list", "schedule_uplift_production"],
        pivot=True,
    )
    async def activate_promotion(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT: shelf prices change in stores."""
        logger.info(f"🔒 [{ctx.get('promo_id')}] PIVOT: promotion live at {ctx.get('retailer')}")
        await asyncio.sleep(0.1)
        return {"live": True}

    @action("settle_deductions", depends_on=["activate_promotion"])
    async def settle_deductions(self, ctx: SagaContext) -> dict[str, Any]:
        logger.info(f"📑 [{ctx.get('promo_id')}] Matching the retailer's deductions to the funding")
        await asyncio.sleep(0.05)
        return {"settled": ctx.get("funding")}


async def main() -> None:
    promo = {
        "promo_id": "TPR-SUMMER-07",
        "retailer": "GROCER-01",
        "discount_per_unit": "0.50",
        "expected_units": 80_000,
    }
    logger.info("=== Promotion that goes live ===")
    await TradePromotionSaga().run(dict(promo))

    logger.info("=== The co-packer's line is down: budget, terms and prices are restored ===")
    try:
        await TradePromotionSaga().run({**promo, "line_down": True})
    except SagaFailedError as e:
        logger.info(f"Promotion cancelled: {e}")


if __name__ == "__main__":
    asyncio.run(main())
