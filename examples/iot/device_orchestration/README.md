# IoT Device Orchestration Saga

Smart home "Leaving Home" routine orchestrating 100+ devices with automatic rollback and safe state maintenance.

## Overview

This example demonstrates coordinated control of multiple IoT devices across different protocols (Z-Wave, Zigbee, MQTT) with proper compensation handling to maintain home safety.

## Use Case

When a homeowner leaves home, the system should:
1. Secure the home (lock doors, arm security)
2. Save energy (adjust thermostat, turn off lights)
3. Maintain safety (never leave home in partial/unsafe state)

## Workflow

```
Leaving Home Routine Started
    ↓
[1] Lock All Doors (Z-Wave) → (Compensation: Unlock for emergency access)
    ↓
[2] Set Thermostat to Away Mode (Zigbee) → (Compensation: Restore comfortable temp)
    ↓
[3] Turn Off 100+ Lights (Zigbee/MQTT) → (Compensation: Restore previous state)
    ↓
[4] Arm Security System → (Compensation: Disarm to prevent false alarms)
    ↓
[5] Send Notification (idempotent)
    ↓
Routine Complete
```

## Key Features

### Multi-Protocol Support
- **Z-Wave**: Door locks, deadbolts
- **Zigbee**: Lights, thermostats, sensors
- **MQTT**: Custom IoT devices, bridges

### Safe State Maintenance
- **No Partial Execution**: All steps complete or all rollback
- **Emergency Access**: Doors unlock on any failure
- **Climate Safety**: Thermostat restored if routine fails
- **Lighting Safety**: Lights restored for occupant safety

### Device Coordination
- Orchestrates 100+ devices in correct sequence
- Handles device dependencies (must lock doors before arming security)
- Manages protocol-specific timing and retries

## Files

- **main.py** - Complete saga implementation with demo scenarios

## Usage

```python
from examples.iot_device_orchestration.main import IoTDeviceOrchestrationSaga

# Create leaving home routine
saga = IoTDeviceOrchestrationSaga(
    routine_id="ROUTINE-001",
    home_id="HOME-123",
    user_id="USER-456",
    device_count=100,
    simulate_failure=False
)

# Execute routine
result = await saga.run({"routine_id": saga.routine_id})
```

## Running the Example

```bash
python examples/iot_device_orchestration/main.py
```

Expected output shows:
1. **Scenario 1**: Successful routine execution
2. **Scenario 2**: Device failure with automatic rollback

## Actions

### lock_doors(ctx)
Locks all doors using Z-Wave protocol.

**Returns:**
```python
{
    "locked_doors": [
        {"device_id": "DOOR-1", "protocol": "Z-Wave", "status": "locked"},
        # ... more doors
    ],
    "protocol": "Z-Wave",
    "timestamp": "2026-01-01T14:30:00Z"
}
```

### set_thermostat_away(ctx)
Sets thermostat to energy-saving away mode.

**Returns:**
```python
{
    "device_id": "THERM-MAIN",
    "protocol": "Zigbee",
    "previous_temp": 72,
    "away_temp": 65,
    "mode": "away"
}
```

### turn_off_lights(ctx)
Turns off all lights across multiple protocols.

**Returns:**
```python
{
    "lights": [
        {
            "device_id": "LIGHT-1",
            "protocol": "Zigbee",
            "room": "Living Room",
            "previous_state": "on",
            "brightness": 0
        },
        # ... 100+ more lights
    ],
    "total_count": 100
}
```

### arm_security_system(ctx)
Arms security system with all sensors active.

**Returns:**
```python
{
    "system_id": "SEC-MAIN",
    "mode": "away",
    "sensors_active": ["motion", "door", "window", "glass_break"],
    "armed_zones": [1, 2, 3, ..., 10],
    "alarm_code": "ARM-ROUTINE-001"
}
```

### send_notification(ctx)
Sends confirmation to homeowner (idempotent - no compensation needed).

**Returns:**
```python
{
    "user_id": "USER-456",
    "title": "🏠 Leaving Home Complete",
    "message": "All 100+ devices secured...",
    "channels": ["push", "email"]
}
```

## Compensations

### unlock_doors(ctx)
**Emergency Safety**: Unlocks doors on failure to ensure emergency access.

### restore_thermostat(ctx)
Restores thermostat to previous comfortable temperature.

### restore_lights(ctx)
Restores previous lighting state for safety (prevents leaving home dark).

### disarm_security_system(ctx)
Disarms security to prevent false alarms from restored state.

## Error Scenarios

### Device Communication Failure
If any device fails to respond (e.g., lighting controller hub offline):
- All previous steps are compensated in reverse order
- Doors unlock for safety
- Thermostat restored
- Home returned to "occupied" state

### Protocol Timeout
If Z-Wave/Zigbee communication times out:
- Saga automatically retries with exponential backoff
- If retry limit exceeded, triggers compensation

### Partial State Prevention
The saga ensures the home is never left in a partial state:
- ❌ **Bad**: Doors locked but security not armed
- ✅ **Good**: Either fully secured or fully restored to occupied state

## Real-World Integration

### MQTT Broker
```python
import asyncio
import aiomqtt

async def lock_door_via_mqtt(device_id: str):
    async with aiomqtt.Client("mqtt.home.local") as client:
        await client.publish(f"zigbee2mqtt/{device_id}/set", '{"state": "LOCK"}')
```

### Z-Wave Controller
```python
import aiohttp

async def lock_door_via_zwave(device_id: str):
    async with aiohttp.ClientSession() as session:
        await session.post(
            f"http://zwave-controller.local/api/devices/{device_id}/lock",
            headers={"Authorization": "Bearer <token>"}
        )
```

### Home Assistant
```python
async def call_home_assistant_service(service: str, entity_id: str):
    async with aiohttp.ClientSession() as session:
        await session.post(
            "http://homeassistant.local:8123/api/services/lock/lock",
            headers={"Authorization": "Bearer <token>"},
            json={"entity_id": entity_id}
        )
```

## Testing

```bash
# Run with default settings
python examples/iot_device_orchestration/main.py

# Test with custom device count
python -c "
import asyncio
from examples.iot_device_orchestration.main import IoTDeviceOrchestrationSaga

async def test():
    saga = IoTDeviceOrchestrationSaga(
        routine_id='TEST-001',
        home_id='HOME-TEST',
        user_id='USER-TEST',
        device_count=250,  # Test with more devices
        simulate_failure=False
    )
    result = await saga.run({'routine_id': saga.routine_id})
    print(f'Result: {result}')

asyncio.run(test())
"
```

## Related Examples

- **Travel Booking** - Multi-service orchestration patterns
- **Healthcare Patient Onboarding** - Compliance and audit trails
- **Smart Grid Energy** - Distributed device coordination

## Best Practices

1. **Always prioritize safety in compensations** (e.g., unlock doors on failure)
2. **Use protocol-appropriate timeouts** (Z-Wave slower than local network)
3. **Implement idempotent operations** where possible
4. **Log all device state changes** for debugging
5. **Test failure scenarios** extensively for each device type

---

**Questions?** Check the [main documentation](../../README.md) or open an issue.
