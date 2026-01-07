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
from sagaz.pivot import RecoveryAction
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Simulation Helpers
# =============================================================================

class StreamingPlatformSimulator:
    """Simulates a live streaming platform (like Twitch, YouTube Live)."""
    
    @staticmethod
    async def validate_event(event_id: str, scheduled_time: str) -> dict:
        """Validate streaming event configuration."""
        await asyncio.sleep(0.05)
        return {
            "valid": True,
            "event_id": event_id,
            "estimated_viewers": 10000,
            "region": "global",
        }
    
    @staticmethod
    async def reserve_capacity(
        estimated_viewers: int,
        regions: list[str],
    ) -> dict:
        """Reserve CDN and encoding capacity."""
        await asyncio.sleep(0.1)
        return {
            "reservation_id": f"CAP-{datetime.now().strftime('%H%M%S')}",
            "cdn_nodes": ["us-east", "eu-west", "ap-northeast"],
            "encoder_pool": "high-capacity",
            "max_bitrate": "8000kbps",
        }
    
    @staticmethod
    async def configure_encoders(
        stream_key: str,
        quality_profiles: list[str],
    ) -> dict:
        """Configure live encoders for multi-bitrate streaming."""
        await asyncio.sleep(0.15)
        return {
            "encoder_id": f"ENC-{stream_key[:8]}",
            "profiles": quality_profiles,
            "primary_encoder": "encoder-01",
            "backup_encoder": "encoder-02",
            "status": "ready",
        }
    
    @staticmethod
    async def warmup_cdn(cdn_nodes: list[str], stream_key: str) -> dict:
        """Pre-warm CDN edge nodes for low-latency delivery."""
        await asyncio.sleep(0.2)
        return {
            "warmup_id": f"CDN-WARM-{stream_key[:8]}",
            "nodes_ready": cdn_nodes,
            "latency_target_ms": 3000,
            "cache_status": "primed",
        }
    
    @staticmethod
    async def start_broadcast(
        stream_key: str,
        title: str,
    ) -> dict:
        """Start the live broadcast - IRREVERSIBLE once live."""
        await asyncio.sleep(0.3)
        return {
            "broadcast_id": f"LIVE-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "stream_url": f"https://stream.example.com/live/{stream_key}",
            "status": "live",
            "go_live_time": datetime.now().isoformat(),
            "viewer_count": 0,
        }
    
    @staticmethod
    async def monitor_stream(broadcast_id: str) -> dict:
        """Monitor stream health metrics."""
        await asyncio.sleep(0.2)
        
        import random
        # Simulate varying viewer counts and health
        viewer_count = random.randint(5000, 15000)
        dropped_frames = random.randint(0, 5)
        
        return {
            "broadcast_id": broadcast_id,
            "current_viewers": viewer_count,
            "peak_viewers": viewer_count + 2000,
            "bitrate_kbps": 6500,
            "dropped_frames": dropped_frames,
            "health_score": 98 if dropped_frames < 3 else 85,
            "duration_seconds": 300,
        }
    
    @staticmethod
    async def archive_to_vod(broadcast_id: str, title: str) -> dict:
        """Archive completed stream as Video on Demand."""
        await asyncio.sleep(0.15)
        return {
            "vod_id": f"VOD-{broadcast_id}",
            "title": title,
            "duration_seconds": 3600,
            "status": "processing",
            "available_at": datetime.now().isoformat(),
        }


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
            raise SagaStepError(f"Invalid event configuration: {event_id}")
        
        logger.info(
            f"✅ [{event_id}] Event validated, "
            f"estimated {result['estimated_viewers']:,} viewers"
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
        
        logger.info(
            f"✅ [{event_id}] LIVE! Broadcast ID: {result['broadcast_id']}"
        )
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
    async def handle_stream_failure(
        self, ctx: SagaContext, error: Exception
    ) -> RecoveryAction:
        """
        Forward recovery for stream health issues.
        
        Strategies:
        1. RETRY - Check health again
        2. RETRY_WITH_ALTERNATE - Switch to backup encoder
        3. SKIP - Continue with reduced quality
        4. MANUAL_INTERVENTION - Operations team needed
        """
        error_type = getattr(error, 'type', 'unknown')
        
        if error_type == "encoder_failure":
            if ctx.get("backup_encoder"):
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
    print("=" * 80)
    print("📺 Live Streaming Saga Demo")
    print("=" * 80)
    print("\nThis example demonstrates real-time broadcast as a pivot point.")
    print("Once viewers are watching, you cannot 'undo' what they've seen.\n")
    
    saga = LiveStreamingSaga()
    
    # Scenario 1: Successful live stream
    print("\n" + "=" * 80)
    print("🟢 Scenario 1: Successful Live Stream")
    print("=" * 80)
    
    result = await saga.run({
        "event_id": "EVENT-2026-001",
        "stream_key": "sk_a1b2c3d4e5f6",
        "title": "🎮 Epic Gaming Championship Finals",
        "scheduled_time": datetime.now().isoformat(),
        "quality_profiles": ["1080p", "720p", "480p", "360p"],
        "estimated_viewers": 50000,
    })
    
    print(f"\n{'✅' if result.get('saga_id') else '❌'} Stream Result:")
    print(f"   Saga ID: {result.get('saga_id')}")
    print(f"   Broadcast: {result.get('broadcast_id', 'N/A')}")
    print(f"   Stream URL: {result.get('stream_url', 'N/A')}")
    print(f"   Peak Viewers: {result.get('peak_viewers', 'N/A'):,}")
    print(f"   VOD: {result.get('vod_id', 'N/A')}")
    print(f"   Pivot Reached: {result.get('pivot_reached', False)}")
    
    # Scenario 2: Pre-pivot failure
    print("\n" + "=" * 80)
    print("🟡 Scenario 2: Pre-Pivot Failure (Capacity Issue)")
    print("=" * 80)
    print("If capacity reservation fails before going live:\n")
    print("  → Event validation cancelled")
    print("  → No stream started (pivot not reached)")
    print("  → Resources cleanly released")
    print("  → Can retry with different configuration")
    
    # Scenario 3: Post-pivot scenarios
    print("\n" + "=" * 80)
    print("🔴 Scenario 3: Post-Pivot Scenarios (During Live Stream)")
    print("=" * 80)
    print("""
In a real implementation (when ADR-023 is complete), issues during
the live stream would use forward recovery:

1. Encoder Failure:
   → Switch to backup encoder seamlessly
   → Viewers may see brief quality drop

2. CDN Partial Outage:
   → Route around failed edge nodes
   → Reduce quality if needed (1080p → 720p)

3. Monitoring Failure:
   → Continue stream (show must go on!)
   → Alert operations team
   → Log for post-mortem

Key insight: Unlike traditional sagas, we NEVER roll back a live stream.
Viewers have already seen content. We can only:
- Continue with degraded quality
- Gracefully end the stream
- Archive what was broadcast
""")
    
    print("\n" + "=" * 80)
    print("Demo Complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
