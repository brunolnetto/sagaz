# Live Streaming Saga

**Category:** Media/Content  
**Pivot Type:** Real-Time Event

## Description

This saga demonstrates a live streaming workflow where going live is the **point of no return**. Once viewers are watching, you cannot "undo" what they've already seen - only forward recovery strategies apply.

## Saga Flow

```
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────────┐
│ validate_event    │ ──→ │reserve_capacity │ ──→ │ configure_encoders  │
│ (reversible)      │     │ (reversible)    │     │ (reversible)        │
└───────────────────┘     └─────────────────┘     └──────────┬──────────┘
                                                             │
                          ┌──────────────────────────────────┘
                          ↓
                    ┌─────────────────┐
                    │ warmup_cdn      │
                    │ (reversible)    │
                    └────────┬────────┘
                             │
┌────────────────────────────┘
↓
┌─────────────────────────────┐     ┌───────────────────┐     ┌───────────────┐
│ go_live                     │ ──→ │ monitor_stream    │ ──→ │ archive_vod   │
│ 🔒 PIVOT (stream active,    │     │ (forward only)    │     │ (forward only)│
│   viewers connected)        │     │                   │     │               │
└─────────────────────────────┘     └───────────────────┘     └───────────────┘
```

## Pivot Step: `go_live`

Once the broadcast goes live:

### Why It's Irreversible

- Stream is public, accessible to viewers worldwide
- Content is being watched in real-time
- Cannot "un-see" what viewers have already watched
- CDN has cached and distributed content globally

### What Happens After Pivot

- Must continue stream or gracefully end
- Quality issues require real-time adaptation
- Cannot compensate - only forward recovery

## Forward Recovery Strategies

| Scenario | Strategy | Action |
|----------|----------|--------|
| Encoder failure | RETRY_WITH_ALTERNATE | Switch to backup encoder |
| CDN partial outage | SKIP | Route around, reduce quality |
| Monitoring failure | CONTINUE | Alert ops, stream continues |
| Critical failure | MANUAL_INTERVENTION | Gracefully end stream |

## Usage

```python
from examples.media.live_streaming import LiveStreamingSaga
from datetime import datetime

saga = LiveStreamingSaga()

result = await saga.run({
    "event_id": "EVENT-2026-001",
    "stream_key": "sk_a1b2c3d4e5f6",
    "title": "Epic Gaming Championship Finals",
    "scheduled_time": datetime.now().isoformat(),
    "quality_profiles": ["1080p", "720p", "480p"],
    "estimated_viewers": 50000,
})
```

## Context Schema

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | str | Unique event identifier |
| `stream_key` | str | Stream key for the broadcast |
| `title` | str | Stream title |
| `scheduled_time` | str | Scheduled start time (ISO format) |
| `quality_profiles` | list[str] | Quality levels |
| `estimated_viewers` | int | Expected viewer count |

## Running the Example

```bash
python examples/media/live_streaming/main.py
```

## Key Concepts Demonstrated

1. **Real-Time Irreversibility**: Live broadcast cannot be "undone"
2. **CDN Pre-Warming**: Preparing edge nodes for low latency
3. **Multi-Bitrate Encoding**: Adaptive streaming setup
4. **Graceful Degradation**: Reducing quality vs. losing stream
5. **VOD Archival**: Post-stream content preservation
