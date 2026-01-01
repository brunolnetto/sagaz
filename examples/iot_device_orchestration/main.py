"""
IoT Device Orchestration Saga Example

Demonstrates smart home "Leaving Home" routine orchestrating 100+ devices
with multi-device coordination, automatic rollback, and safe state maintenance.
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
    """Smart home 'Leaving Home' routine with multi-device coordination."""

    saga_name = "iot-device-orchestration"

    def __init__(
        self,
        routine_id: str,
        home_id: str,
        user_id: str,
        device_count: int = 100,
        simulate_failure: bool = False,
    ):
        super().__init__()
        self.routine_id = routine_id
        self.home_id = home_id
        self.user_id = user_id
        self.device_count = device_count
        self.simulate_failure = simulate_failure

    @action("lock_doors")
    async def lock_doors(self, ctx: SagaContext) -> dict[str, Any]:
        """Lock all doors using Z-Wave protocol."""
        logger.info(f"🚪 Locking all doors for home {self.home_id}")
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
        logger.warning(f"🔓 EMERGENCY: Unlocking doors for home {self.home_id}")

        locked_doors = ctx.get("locked_doors", [])
        for door in locked_doors:
            logger.info(f"   Unlocking {door['device_id']}")

        await asyncio.sleep(0.1)

    @action("set_thermostat_away", depends_on=["lock_doors"])
    async def set_thermostat_away(self, ctx: SagaContext) -> dict[str, Any]:
        """Set thermostat to away mode (energy saving)."""
        logger.info(f"🌡️  Setting thermostat to away mode for home {self.home_id}")
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
        logger.warning(f"🌡️  Restoring thermostat for home {self.home_id}")

        previous_temp = ctx.get("previous_temp", 72)
        device_id = ctx.get("device_id", "THERM-MAIN")
        logger.info(f"   Restoring {device_id} to {previous_temp}°F")

        await asyncio.sleep(0.1)

    @action("turn_off_lights", depends_on=["set_thermostat_away"])
    async def turn_off_lights(self, ctx: SagaContext) -> dict[str, Any]:
        """Turn off all lights to save energy."""
        logger.info(f"💡 Turning off all lights for home {self.home_id}")
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
            for i in range(1, self.device_count + 1)
        ]

        if self.simulate_failure:
            raise SagaStepError("Communication failure with lighting controller hub")

        logger.info(f"   ✅ Turned off {len(lights_off)} lights")
        return {"lights": lights_off, "total_count": len(lights_off)}

    @compensate("turn_off_lights")
    async def restore_lights(self, ctx: SagaContext) -> None:
        """Restore previous lighting state for safety."""
        logger.warning(f"💡 Restoring lights for home {self.home_id}")

        lights = ctx.get("lights", [])
        for light in lights[:5]:  # Log first 5
            logger.info(f"   Restoring {light['device_id']} to {light['previous_state']}")

        logger.info(f"   ... and {len(lights) - 5} more lights")
        await asyncio.sleep(0.15)

    @action("arm_security_system", depends_on=["turn_off_lights"])
    async def arm_security_system(self, ctx: SagaContext) -> dict[str, Any]:
        """Arm security system with motion detection."""
        logger.info(f"🔐 Arming security system for home {self.home_id}")
        await asyncio.sleep(0.15)

        security_config = {
            "system_id": "SEC-MAIN",
            "mode": "away",
            "sensors_active": ["motion", "door", "window", "glass_break"],
            "armed_zones": list(range(1, 11)),  # 10 zones
            "alarm_code": f"ARM-{self.routine_id}",
        }

        logger.info(f"   ✅ Security armed with {len(security_config['sensors_active'])} sensor types")
        return security_config

    @compensate("arm_security_system")
    async def disarm_security_system(self, ctx: SagaContext) -> None:
        """Disarm security system to prevent false alarms."""
        logger.warning(f"🔓 Disarming security system for home {self.home_id}")

        system_id = ctx.get("system_id", "SEC-MAIN")
        logger.info(f"   Disarming {system_id}")

        await asyncio.sleep(0.1)

    @action("send_notification", depends_on=["arm_security_system"])
    async def send_notification(self, ctx: SagaContext) -> dict[str, Any]:
        """Send confirmation notification to homeowner (idempotent)."""
        logger.info(f"📱 Sending notification to user {self.user_id}")
        await asyncio.sleep(0.05)

        notification = {
            "user_id": self.user_id,
            "title": "🏠 Leaving Home Complete",
            "message": f"All {self.device_count}+ devices secured. Home {self.home_id} is safe.",
            "channels": ["push", "email"],
        }

        logger.info(f"   ✅ Notification sent via {', '.join(notification['channels'])}")
        return notification


async def main():
    """Run the IoT device orchestration saga demo."""
    print("=" * 80)
    print("IoT Device Orchestration Saga Demo - Smart Home 'Leaving Home' Routine")
    print("=" * 80)

    # Scenario 1: Successful execution
    print("\n🟢 Scenario 1: Successful Leaving Home Routine")
    print("-" * 80)

    saga_success = IoTDeviceOrchestrationSaga(
        routine_id="ROUTINE-001",
        home_id="HOME-123",
        user_id="USER-456",
        device_count=100,
        simulate_failure=False,
    )

    result_success = await saga_success.run({"routine_id": saga_success.routine_id})

    print(f"\n{'✅' if result_success.get('saga_id') else '❌'} Leaving Home Routine Result:")
    print(f"   Saga ID: {result_success.get('saga_id')}")
    print(f"   Routine ID: {result_success.get('routine_id')}")
    print(f"   Status: All {saga_success.device_count} devices secured")

    # Scenario 2: Failure with automatic rollback
    print("\n\n🔴 Scenario 2: Device Failure with Automatic Rollback")
    print("-" * 80)

    saga_failure = IoTDeviceOrchestrationSaga(
        routine_id="ROUTINE-002",
        home_id="HOME-123",
        user_id="USER-456",
        device_count=100,
        simulate_failure=True,  # Simulate failure at lights step
    )

    try:
        result_failure = await saga_failure.run({"routine_id": saga_failure.routine_id})
    except Exception as e:
        result_failure = {}

    print(f"\n{'❌' if not result_failure.get('saga_id') else '✅'} Rollback Result:")
    print(f"   Saga ID: {result_failure.get('saga_id', 'N/A')}")
    print(f"   Routine ID: {saga_failure.routine_id}")
    print("   Status: Failed and rolled back - home returned to safe state")
    print("   Safety: Doors unlocked, thermostat restored for occupant comfort")

    print("\n" + "=" * 80)
    print("Key Features Demonstrated:")
    print("  ✅ Multi-device coordination (100+ devices)")
    print("  ✅ Multiple protocol support (Z-Wave, Zigbee, MQTT)")
    print("  ✅ Automatic rollback maintains safe state")
    print("  ✅ No partial execution - all or nothing")
    print("  ✅ Emergency access preserved (doors unlock on failure)")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
