"""
Live Streaming Saga Example

Demonstrates real-time event as a pivot point. Once a live stream goes live
(viewers connected, broadcast active), the stream cannot be "undone" -
viewers have already seen the content.

Pivot Step: go_live
    Stream is public, viewers are watching.
    Cannot "undo" that content was broadcast.
    Must handle gracefully (end stream, not rollback).

Forward Recovery:
    - Encoder failure: Switch to backup encoder
    - CDN partial failure: Reduce quality, skip problematic edge
    - Monitoring failure: Continue stream, alert operations
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate, forward_recovery
from sagaz.core.exceptions import SagaStepError
from sagaz.core.execution.pivot import RecoveryAction
from sagaz.examples.digital_media.media.live_streaming.simulator import StreamingPlatformSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Saga Definition
# =============================================================================


class LiveStreamingSaga(Saga):
    """
    Live streaming saga with real-time event pivot.

    This saga demonstrates the irreversibility of live broadcasts.
    Once a stream goes live, viewers are watching in real-time.
    You cannot "undo" what viewers have already seen.

    Expected context:
        - event_id: str - Unique event identifier
        - stream_key: str - Stream key for the broadcast
        - title: str - Stream title
        - scheduled_time: str - Scheduled start time
        - quality_profiles: list[str] - Quality levels ["1080p", "720p", "480p"]
        - estimated_viewers: int - Expected viewer count
    """

    saga_name = "live-streaming"

    # === REVERSIBLE ZONE ===

    @action("validate_event")
    async def validate_event(self, ctx: SagaContext) -> dict[str, Any]:
        """Validate streaming event configuration."""
        event_id = ctx.get("event_id")
        scheduled_time = ctx.get("scheduled_time", datetime.now().isoformat())

        logger.info(f"📋 [{event_id}] Validating streaming event...")

        result = await StreamingPlatformSimulator.validate_event(event_id, scheduled_time)

        if not result["valid"]:
            msg = f"Invalid event configuration: {event_id}"
            raise SagaStepError(msg)

        logger.info(
            f"✅ [{event_id}] Event validated, estimated {result['estimated_viewers']:,} viewers"
        )

        return {
            "estimated_viewers": result["estimated_viewers"],
            "broadcast_region": result["region"],
        }

    @compensate("validate_event")
    async def cancel_event(self, ctx: SagaContext) -> None:
        """Cancel event validation."""
        event_id = ctx.get("event_id")
        logger.warning(f"↩️ [{event_id}] Cancelling event validation...")
        await asyncio.sleep(0.05)

    @action("reserve_capacity", depends_on=["validate_event"])
    async def reserve_capacity(self, ctx: SagaContext) -> dict[str, Any]:
        """Reserve CDN and encoding capacity."""
        event_id = ctx.get("event_id")
        estimated_viewers = ctx.get("estimated_viewers", 10000)

        logger.info(f"📡 [{event_id}] Reserving capacity for {estimated_viewers:,} viewers...")

        result = await StreamingPlatformSimulator.reserve_capacity(
            estimated_viewers,
            ["us", "eu", "ap"],
        )

        logger.info(
            f"✅ [{event_id}] Capacity reserved: {result['reservation_id']}, "
            f"CDN nodes: {len(result['cdn_nodes'])}"
        )

        return {
            "capacity_reservation_id": result["reservation_id"],
            "cdn_nodes": result["cdn_nodes"],
            "encoder_pool": result["encoder_pool"],
            "max_bitrate": result["max_bitrate"],
        }

    @compensate("reserve_capacity")
    async def release_capacity(self, ctx: SagaContext) -> None:
        """Release reserved capacity."""
        event_id = ctx.get("event_id")
        reservation_id = ctx.get("capacity_reservation_id")

        logger.warning(f"↩️ [{event_id}] Releasing capacity {reservation_id}...")
        await asyncio.sleep(0.1)
        logger.info(f"✅ [{event_id}] Capacity released")

    @action("configure_encoders", depends_on=["reserve_capacity"])
    async def configure_encoders(self, ctx: SagaContext) -> dict[str, Any]:
        """Configure live encoders for multi-bitrate streaming."""
        event_id = ctx.get("event_id")
        stream_key = ctx.get("stream_key", f"sk_{event_id}")
        quality_profiles = ctx.get("quality_profiles", ["1080p", "720p", "480p"])

        logger.info(f"🎬 [{event_id}] Configuring encoders for {quality_profiles}...")

        result = await StreamingPlatformSimulator.configure_encoders(
            stream_key,
            quality_profiles,
        )

        logger.info(
            f"✅ [{event_id}] Encoders ready: {result['encoder_id']}, "
            f"backup: {result['backup_encoder']}"
        )

        return {
            "encoder_id": result["encoder_id"],
            "primary_encoder": result["primary_encoder"],
            "backup_encoder": result["backup_encoder"],
            "encoder_status": result["status"],
        }

    @compensate("configure_encoders")
    async def teardown_encoders(self, ctx: SagaContext) -> None:
        """Teardown encoder configuration."""
        event_id = ctx.get("event_id")
        encoder_id = ctx.get("encoder_id")

        logger.warning(f"↩️ [{event_id}] Tearing down encoders {encoder_id}...")
        await asyncio.sleep(0.1)

    @action("warmup_cdn", depends_on=["configure_encoders"])
    async def warmup_cdn(self, ctx: SagaContext) -> dict[str, Any]:
        """Pre-warm CDN edge nodes for low-latency delivery."""
        event_id = ctx.get("event_id")
        cdn_nodes = ctx.get("cdn_nodes", [])
        stream_key = ctx.get("stream_key", f"sk_{event_id}")

        logger.info(f"🌐 [{event_id}] Warming up {len(cdn_nodes)} CDN nodes...")

        result = await StreamingPlatformSimulator.warmup_cdn(cdn_nodes, stream_key)

        logger.info(
            f"✅ [{event_id}] CDN warmed up: {result['warmup_id']}, "
            f"latency target: {result['latency_target_ms']}ms"
        )

        return {
            "cdn_warmup_id": result["warmup_id"],
            "nodes_ready": result["nodes_ready"],
            "latency_target_ms": result["latency_target_ms"],
        }

    @compensate("warmup_cdn")
    async def cooldown_cdn(self, ctx: SagaContext) -> None:
        """Release CDN warmup resources."""
        event_id = ctx.get("event_id")
        warmup_id = ctx.get("cdn_warmup_id")

        logger.warning(f"↩️ [{event_id}] Releasing CDN warmup {warmup_id}...")
        await asyncio.sleep(0.05)

    # === PIVOT STEP ===

    @action("go_live", depends_on=["warmup_cdn"], pivot=True)
    async def go_live(self, ctx: SagaContext) -> dict[str, Any]:
        """
        🔒 PIVOT STEP: Start the live broadcast.

        Once this step completes, the stream is PUBLIC and viewers
        are watching in real-time. Cannot "undo" what viewers have seen.
        Must handle gracefully (end stream, not rollback).
        """
        event_id = ctx.get("event_id")
        stream_key = ctx.get("stream_key", f"sk_{event_id}")
        title = ctx.get("title", "Live Stream")

        logger.info(f"🔒 [{event_id}] PIVOT: Going LIVE!")
        logger.info(f"   🎥 '{title}'")

        result = await StreamingPlatformSimulator.start_broadcast(stream_key, title)

        logger.info(f"✅ [{event_id}] LIVE! Broadcast ID: {result['broadcast_id']}")
        logger.info(f"   📺 Watch at: {result['stream_url']}")

        return {
            "broadcast_id": result["broadcast_id"],
            "stream_url": result["stream_url"],
            "go_live_time": result["go_live_time"],
            "pivot_reached": True,  # Point of no return
        }

    # Note: No compensation for go_live - it's a pivot step!
    # Viewers have already seen the stream. Can only end, not undo.

    # === COMMITTED ZONE (Forward Recovery Only) ===

    @action("monitor_stream", depends_on=["go_live"])
    async def monitor_stream(self, ctx: SagaContext) -> dict[str, Any]:
        """Monitor stream health and viewer metrics."""
        event_id = ctx.get("event_id")
        broadcast_id = ctx.get("broadcast_id")

        logger.info(f"📊 [{event_id}] Monitoring stream health...")

        result = await StreamingPlatformSimulator.monitor_stream(broadcast_id)

        health_emoji = "🟢" if result["health_score"] >= 90 else "🟡"

        logger.info(
            f"✅ [{event_id}] Stream stats: "
            f"{health_emoji} Health {result['health_score']}%, "
            f"👥 {result['current_viewers']:,} viewers, "
            f"📶 {result['bitrate_kbps']}kbps"
        )

        return {
            "current_viewers": result["current_viewers"],
            "peak_viewers": result["peak_viewers"],
            "health_score": result["health_score"],
            "dropped_frames": result["dropped_frames"],
            "stream_duration_seconds": result["duration_seconds"],
        }

    @forward_recovery("monitor_stream")
    async def handle_stream_failure(self, ctx: SagaContext, error: Exception) -> RecoveryAction:
        """
        Forward recovery for stream health issues.

        Strategies:
        1. RETRY - Check health again
        2. RETRY_WITH_ALTERNATE - Switch to backup encoder
        3. SKIP - Continue with reduced quality
        4. MANUAL_INTERVENTION - Operations team needed
        """
        error_type = getattr(error, "type", "unknown")

        if error_type == "encoder_failure" and ctx.get("backup_encoder"):
            ctx.set("use_backup_encoder", True)
            logger.info("🔄 Switching to backup encoder...")
            return RecoveryAction.RETRY_WITH_ALTERNATE

        if error_type == "cdn_partial":
            ctx.set("quality", "720p")  # Reduce quality
            logger.info("📉 Reducing quality to 720p...")
            return RecoveryAction.SKIP

        return RecoveryAction.MANUAL_INTERVENTION

    @action("archive_to_vod", depends_on=["monitor_stream"])
    async def archive_to_vod(self, ctx: SagaContext) -> dict[str, Any]:
        """Archive completed stream as Video on Demand."""
        event_id = ctx.get("event_id")
        broadcast_id = ctx.get("broadcast_id")
        title = ctx.get("title", "Live Stream")

        logger.info(f"💾 [{event_id}] Archiving stream to VOD...")

        result = await StreamingPlatformSimulator.archive_to_vod(broadcast_id, title)

        logger.info(
            f"✅ [{event_id}] VOD created: {result['vod_id']}, "
            f"duration: {result['duration_seconds']}s"
        )

        return {
            "vod_id": result["vod_id"],
            "vod_status": result["status"],
            "vod_available_at": result["available_at"],
        }


# =============================================================================
# Demo Scenarios
# =============================================================================


async def main():
    """Run the live streaming saga demo."""

    saga = LiveStreamingSaga()

    # Scenario 1: Successful live stream

    await saga.run(
        {
            "event_id": "EVENT-2026-001",
            "stream_key": "sk_a1b2c3d4e5f6",
            "title": "🎮 Epic Gaming Championship Finals",
            "scheduled_time": datetime.now().isoformat(),
            "quality_profiles": ["1080p", "720p", "480p", "360p"],
            "estimated_viewers": 50000,
        }
    )

    # Scenario 2: Pre-pivot failure

    # Scenario 3: Post-pivot scenarios


if __name__ == "__main__":
    asyncio.run(main())
