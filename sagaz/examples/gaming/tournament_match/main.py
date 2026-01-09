"""
Tournament Match Saga Example

Demonstrates real-time competitive event as pivot point.
Once match starts, players are committed and bracket is locked.

Pivot Step: start_match
    Match timer starts, tournament bracket locked.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TournamentMatchSaga(Saga):
    """Tournament match saga with match start pivot."""

    saga_name = "tournament-match"

    @action("validate_players")
    async def validate_players(self, ctx: SagaContext) -> dict[str, Any]:
        match_id = ctx.get("match_id")
        logger.info(f"🎮 [{match_id}] Validating players...")
        await asyncio.sleep(0.1)
        return {"players_valid": True, "anti_cheat_verified": True}

    @compensate("validate_players")
    async def release_players(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('match_id')}] Releasing players...")
        await asyncio.sleep(0.05)

    @action("check_eligibility", depends_on=["validate_players"])
    async def check_eligibility(self, ctx: SagaContext) -> dict[str, Any]:
        match_id = ctx.get("match_id")
        logger.info(f"✔️ [{match_id}] Checking eligibility...")
        await asyncio.sleep(0.1)
        return {"all_eligible": True, "rank_verified": True}

    @compensate("check_eligibility")
    async def void_eligibility(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('match_id')}] Voiding eligibility check...")
        await asyncio.sleep(0.05)

    @action("reserve_server", depends_on=["check_eligibility"])
    async def reserve_server(self, ctx: SagaContext) -> dict[str, Any]:
        match_id = ctx.get("match_id")
        logger.info(f"🖥️ [{match_id}] Reserving game server...")
        await asyncio.sleep(0.15)
        return {"server_id": f"SRV-{uuid.uuid4().hex[:8]}", "region": "us-east"}

    @compensate("reserve_server")
    async def release_server(self, ctx: SagaContext) -> None:
        logger.warning(f"↩️ [{ctx.get('match_id')}] Releasing server...")
        await asyncio.sleep(0.05)

    @action("start_match", depends_on=["reserve_server"])
    async def start_match(self, ctx: SagaContext) -> dict[str, Any]:
        """🔒 PIVOT STEP: Start the match - bracket locked."""
        match_id = ctx.get("match_id")
        logger.info(f"🔒 [{match_id}] PIVOT: Starting match!")
        await asyncio.sleep(0.3)
        return {
            "match_started": True,
            "start_time": datetime.now().isoformat(),
            "bracket_locked": True,
            "pivot_reached": True,
        }

    @action("track_progress", depends_on=["start_match"])
    async def track_progress(self, ctx: SagaContext) -> dict[str, Any]:
        match_id = ctx.get("match_id")
        logger.info(f"📊 [{match_id}] Tracking match progress...")
        await asyncio.sleep(0.2)
        return {"scores_recorded": True, "duration_minutes": 45}

    @action("finalize_result", depends_on=["track_progress"])
    async def finalize_result(self, ctx: SagaContext) -> dict[str, Any]:
        match_id = ctx.get("match_id")
        logger.info(f"🏆 [{match_id}] Finalizing result...")
        await asyncio.sleep(0.1)
        return {"winner": "Team A", "score": "3-2", "result_certified": True}

    @action("distribute_prizes", depends_on=["finalize_result"])
    async def distribute_prizes(self, ctx: SagaContext) -> dict[str, Any]:
        match_id = ctx.get("match_id")
        prize_pool = ctx.get("prize_pool", 1000)
        logger.info(f"💰 [{match_id}] Distributing prizes...")
        await asyncio.sleep(0.1)
        return {"prizes_distributed": True, "amount": prize_pool}


async def main():

    saga = TournamentMatchSaga()
    await saga.run({
        "match_id": "MATCH-2026-FINAL",
        "tournament_id": "TOURN-001",
        "team_a": "Team Alpha",
        "team_b": "Team Beta",
        "prize_pool": 5000,
    })



if __name__ == "__main__":
    asyncio.run(main())
