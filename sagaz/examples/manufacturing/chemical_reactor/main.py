"""
Chemical Reactor Saga Example

Demonstrates chemical reaction start as pivot point. Once reagents
are combined, the reaction cannot be stopped - only controlled.

Pivot Step: initiate_reaction
    Reagents combined, reaction started.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any
import uuid

from sagaz import Saga, SagaContext, action, compensate, forward_recovery
from sagaz.pivot import RecoveryAction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ChemicalReactorSaga(Saga):
    """Chemical reactor saga with reaction initiation pivot."""
    
    saga_name = "chemical-reactor"
    
    @action("validate_recipe")
    async def validate_recipe(self, ctx: SagaContext) -> dict[str, Any]:
        batch_id = ctx.get("batch_id")
        logger.info(f"📋 [{batch_id}] Validating recipe...")
        await asyncio.sleep(0.1)
        return {"recipe_valid": True, "reagent_count": 3}
    
    @compensate("validate_recipe")
    async def cancel_recipe(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('batch_id')}] Cancelling recipe...")
        await asyncio.sleep(0.05)
    
    @action("load_reagents", depends_on=["validate_recipe"])
    async def load_reagents(self, ctx: SagaContext) -> dict[str, Any]:
        batch_id = ctx.get("batch_id")
        logger.info(f"🧪 [{batch_id}] Loading reagents...")
        await asyncio.sleep(0.2)
        return {"reagents_loaded": ["A", "B", "C"], "total_volume_liters": 500}
    
    @compensate("load_reagents")
    async def offload_reagents(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('batch_id')}] Offloading reagents...")
        await asyncio.sleep(0.1)
    
    @action("preheat_reactor", depends_on=["load_reagents"])
    async def preheat_reactor(self, ctx: SagaContext) -> dict[str, Any]:
        batch_id = ctx.get("batch_id")
        target_temp = ctx.get("target_temp_c", 85)
        logger.info(f"🌡️ [{batch_id}] Preheating to {target_temp}°C...")
        await asyncio.sleep(0.3)
        return {"reactor_temp_c": target_temp, "pressure_bar": 2.5}
    
    @compensate("preheat_reactor")
    async def cooldown_reactor(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('batch_id')}] Cooling down reactor...")
        await asyncio.sleep(0.2)
    
    @action("initiate_reaction", depends_on=["preheat_reactor"], pivot=True)
    async def initiate_reaction(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Initiate reaction - reagents combined."""
        batch_id = ctx.get("batch_id")
        logger.info(f"🔒 [{batch_id}] PIVOT: Initiating reaction...")
        await asyncio.sleep(0.4)
        return {
            "reaction_started": True,
            "reaction_id": f"RXN-{uuid.uuid4().hex[:8].upper()}",
            "start_time": datetime.now().isoformat(),
            "exothermic": True,
            "pivot_reached": True,
        }
    
    @action("monitor_reaction", depends_on=["initiate_reaction"])
    async def monitor_reaction(self, ctx: SagaContext) -> dict[str, Any]:
        batch_id = ctx.get("batch_id")
        logger.info(f"📊 [{batch_id}] Monitoring reaction progress...")
        await asyncio.sleep(0.3)
        return {
            "conversion_percent": 98.5,
            "temp_stable": True,
            "pressure_stable": True,
        }
    
    @forward_recovery("monitor_reaction")
    async def handle_reaction_anomaly(self, ctx: SagaContext, error: Exception) -> RecoveryAction:
        """Forward recovery for reaction anomalies."""
        batch_id = ctx.get("batch_id")
        logger.warning(f"⚠️ [{batch_id}] Reaction anomaly detected: {error}")
        
        # Emergency cooling
        logger.info(f"❄️ [{batch_id}] Initiating emergency cooling...")
        ctx.set("emergency_cooling", True)
        return RecoveryAction.RETRY
    
    @action("quench_reaction", depends_on=["monitor_reaction"])
    async def quench_reaction(self, ctx: SagaContext) -> dict[str, Any]:
        batch_id = ctx.get("batch_id")
        logger.info(f"💧 [{batch_id}] Quenching reaction...")
        await asyncio.sleep(0.2)
        return {"reaction_quenched": True, "product_yield_kg": 450}
    
    @action("quality_analysis", depends_on=["quench_reaction"])
    async def quality_analysis(self, ctx: SagaContext) -> dict[str, Any]:
        batch_id = ctx.get("batch_id")
        logger.info(f"🔬 [{batch_id}] Running quality analysis...")
        await asyncio.sleep(0.15)
        return {"purity_percent": 99.2, "quality_grade": "A"}


async def main():
    print("=" * 80)
    print("⚗️ Chemical Reactor Saga Demo")
    print("=" * 80)
    
    saga = ChemicalReactorSaga()
    result = await saga.run({
        "batch_id": "BATCH-2026-001",
        "product_code": "CHEM-X42",
        "target_temp_c": 85,
    })
    
    print(f"\n✅ Reactor Result:")
    print(f"   Reaction ID: {result.get('reaction_id', 'N/A')}")
    print(f"   Conversion: {result.get('conversion_percent', 0)}%")
    print(f"   Yield: {result.get('product_yield_kg', 0)} kg")
    print(f"   Purity: {result.get('purity_percent', 0)}%")
    print(f"   Pivot Reached: {result.get('pivot_reached', False)}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
