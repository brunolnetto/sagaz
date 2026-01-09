"""
IoT Device Orchestration Saga Example

Demonstrates smart home "Leaving Home" routine orchestrating 100+ devices
with multi-device coordination, automatic rollback, and safe state maintenance.
Data is passed through the run() method's initial context, not the constructor.
"""

import asyncio
import logging
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class IoTDeviceOrchestrationSaga(Saga):
    """
    Smart home 'Leaving Home' routine with multi-device coordination.

    This saga is stateless - all data is passed through the context via the run() method.

    Expected context:
        - routine_id: str
        - home_id: str
        - user_id: str
        - device_count: int
        - simulate_failure: bool (optional)
    """

    saga_name = "iot-device-orchestration"

    @action("lock_doors")
    async def lock_doors(self, ctx: SagaContext) -> dict[str, Any]:
        """Lock all doors using Z-Wave protocol."""
        home_id = ctx.get("home_id")

        logger.info(f"🚪 Locking all doors for home {home_id}")
        await asyncio.sleep(0.15)

        # Simulate Z-Wave protocol communication
        locked_doors = [
            {"device_id": f"DOOR-{i}", "protocol": "Z-Wave", "status": "locked"}
            for i in range(1, 6)  # 5 doors
        ]

        logger.info(f"   ✅ Locked {len(locked_doors)} doors")
        return {
            "locked_doors": locked_doors,
            "protocol": "Z-Wave",
            "timestamp": "2026-01-01T14:30:00Z",
        }

    @compensate("lock_doors")
    async def unlock_doors(self, ctx: SagaContext) -> None:
        """Unlock doors on failure for safety (emergency access)."""
        home_id = ctx.get("home_id")
        logger.warning(f"🔓 EMERGENCY: Unlocking doors for home {home_id}")

        locked_doors = ctx.get("locked_doors", [])
        for door in locked_doors:
            logger.info(f"   Unlocking {door['device_id']}")

        await asyncio.sleep(0.1)

    @action("set_thermostat_away", depends_on=["lock_doors"])
    async def set_thermostat_away(self, ctx: SagaContext) -> dict[str, Any]:
        """Set thermostat to away mode (energy saving)."""
        home_id = ctx.get("home_id")

        logger.info(f"🌡️  Setting thermostat to away mode for home {home_id}")
        await asyncio.sleep(0.1)

        # Simulate thermostat configuration
        thermostat_config = {
            "device_id": "THERM-MAIN",
            "protocol": "Zigbee",
            "previous_temp": 72,  # Fahrenheit
            "away_temp": 65,
            "mode": "away",
        }

        logger.info(f"   ✅ Thermostat set to {thermostat_config['away_temp']}°F")
        return thermostat_config

    @compensate("set_thermostat_away")
    async def restore_thermostat(self, ctx: SagaContext) -> None:
        """Restore thermostat to previous comfortable temperature."""
        home_id = ctx.get("home_id")
        logger.warning(f"🌡️  Restoring thermostat for home {home_id}")

        previous_temp = ctx.get("previous_temp", 72)
        device_id = ctx.get("device_id", "THERM-MAIN")
        logger.info(f"   Restoring {device_id} to {previous_temp}°F")

        await asyncio.sleep(0.1)

    @action("turn_off_lights", depends_on=["set_thermostat_away"])
    async def turn_off_lights(self, ctx: SagaContext) -> dict[str, Any]:
        """Turn off all lights to save energy."""
        home_id = ctx.get("home_id")
        device_count = ctx.get("device_count", 100)
        simulate_failure = ctx.get("simulate_failure", False)

        logger.info(f"💡 Turning off all lights for home {home_id}")
        await asyncio.sleep(0.2)

        # Simulate controlling many smart bulbs/switches
        lights_off = [
            {
                "device_id": f"LIGHT-{i}",
                "protocol": "Zigbee" if i % 2 == 0 else "MQTT",
                "room": f"Room-{(i % 10) + 1}",
                "previous_state": "on" if i % 3 != 0 else "dimmed",
                "brightness": 0,
            }
            for i in range(1, device_count + 1)
        ]

        if simulate_failure:
            msg = "Communication failure with lighting controller hub"
            raise SagaStepError(msg)

        logger.info(f"   ✅ Turned off {len(lights_off)} lights")
        return {"lights": lights_off, "total_count": len(lights_off)}

    @compensate("turn_off_lights")
    async def restore_lights(self, ctx: SagaContext) -> None:
        """Restore previous lighting state for safety."""
        home_id = ctx.get("home_id")
        logger.warning(f"💡 Restoring lights for home {home_id}")

        lights = ctx.get("lights", [])
        for light in lights[:5]:  # Log first 5
            logger.info(f"   Restoring {light['device_id']} to {light['previous_state']}")

        logger.info(f"   ... and {len(lights) - 5} more lights")
        await asyncio.sleep(0.15)

    @action("arm_security_system", depends_on=["turn_off_lights"])
    async def arm_security_system(self, ctx: SagaContext) -> dict[str, Any]:
        """Arm security system with motion detection."""
        home_id = ctx.get("home_id")
        routine_id = ctx.get("routine_id")

        logger.info(f"🔐 Arming security system for home {home_id}")
        await asyncio.sleep(0.15)

        security_config = {
            "system_id": "SEC-MAIN",
            "mode": "away",
            "sensors_active": ["motion", "door", "window", "glass_break"],
            "armed_zones": list(range(1, 11)),  # 10 zones
            "alarm_code": f"ARM-{routine_id}",
        }

        logger.info(
            f"   ✅ Security armed with {len(security_config['sensors_active'])} sensor types"
        )
        return security_config

    @compensate("arm_security_system")
    async def disarm_security_system(self, ctx: SagaContext) -> None:
        """Disarm security system to prevent false alarms."""
        home_id = ctx.get("home_id")
        logger.warning(f"🔓 Disarming security system for home {home_id}")

        system_id = ctx.get("system_id", "SEC-MAIN")
        logger.info(f"   Disarming {system_id}")

        await asyncio.sleep(0.1)

    @action("send_notification", depends_on=["arm_security_system"])
    async def send_notification(self, ctx: SagaContext) -> dict[str, Any]:
        """Send confirmation notification to homeowner (idempotent)."""
        user_id = ctx.get("user_id")
        home_id = ctx.get("home_id")
        device_count = ctx.get("device_count", 0)

        logger.info(f"📱 Sending notification to user {user_id}")
        await asyncio.sleep(0.05)

        notification = {
            "user_id": user_id,
            "title": "🏠 Leaving Home Complete",
            "message": f"All {device_count}+ devices secured. Home {home_id} is safe.",
            "channels": ["push", "email"],
        }

        logger.info(f"   ✅ Notification sent via {', '.join(notification['channels'])}")
        return notification


async def main():
    """Run the IoT device orchestration saga demo."""

    # Reusable saga instance
    saga = IoTDeviceOrchestrationSaga()

    # Scenario 1: Successful execution

    success_data = {
        "routine_id": "ROUTINE-001",
        "home_id": "HOME-123",
        "user_id": "USER-456",
        "device_count": 100,
        "simulate_failure": False,
    }

    await saga.run(success_data)

    # Scenario 2: Failure with automatic rollback

    failure_data = {
        "routine_id": "ROUTINE-002",
        "home_id": "HOME-123",
        "user_id": "USER-456",
        "device_count": 100,
        "simulate_failure": True,  # Simulate failure at lights step
    }

    try:
        await saga.run(failure_data)
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
