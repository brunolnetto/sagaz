"""
Supply Chain Drone Delivery Saga Example

Demonstrates autonomous drone delivery orchestration with real-time airspace
coordination, battery management, weather checks, and regulatory compliance.
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


class SupplyChainDroneDeliverySaga(Saga):
    """
    Autonomous drone delivery with airspace coordination and regulatory compliance.
    
    This saga is stateless - all data is passed through the context via the run() method.
    
    Expected context:
        - delivery_id: str
        - package_id: str
        - warehouse_id: str
        - destination_lat: float
        - destination_lon: float
        - package_weight_kg: float
        - priority: str
        - simulate_failure: bool (optional)
    """

    saga_name = "supply-chain-drone-delivery"

    @action("reserve_drone")
    async def reserve_drone(self, ctx: SagaContext) -> dict[str, Any]:
        """Reserve available drone from fleet based on package weight and range."""
        delivery_id = ctx.get("delivery_id")
        warehouse_id = ctx.get("warehouse_id")
        
        logger.info(f"🚁 Reserving drone from fleet for delivery {delivery_id}")
        await asyncio.sleep(0.15)

        # Simulate drone selection algorithm
        drone_reservation = {
            "drone_id": "DRONE-42",
            "model": "DeliveryMaster Pro",
            "max_payload_kg": 5.0,
            "battery_level": 95,
            "range_km": 25,
            "current_location": warehouse_id,
            "status": "reserved",
            "reservation_id": f"RES-{delivery_id}",
        }

        logger.info(
            f"   ✅ Reserved {drone_reservation['drone_id']} "
            f"(battery: {drone_reservation['battery_level']}%)"
        )
        return drone_reservation

    @compensate("reserve_drone")
    async def release_drone(self, ctx: SagaContext) -> None:
        """Release drone back to available fleet."""
        delivery_id = ctx.get("delivery_id")
        logger.warning(f"🚁 Releasing drone for delivery {delivery_id}")

        drone_id = ctx.get("drone_id")
        reservation_id = ctx.get("reservation_id")

        logger.info(f"   Returning {drone_id} to fleet (reservation: {reservation_id})")
        logger.info("   Drone status: AVAILABLE")

        await asyncio.sleep(0.1)

    @action("plan_flight_path", depends_on=["reserve_drone"])
    async def plan_flight_path(self, ctx: SagaContext) -> dict[str, Any]:
        """Plan optimal flight path avoiding no-fly zones and obstacles."""
        delivery_id = ctx.get("delivery_id")
        destination_lat = ctx.get("destination_lat")
        destination_lon = ctx.get("destination_lon")
        
        logger.info(f"🗺️  Planning flight path for delivery {delivery_id}")
        await asyncio.sleep(0.2)

        # Simulate flight planning algorithm
        flight_plan = {
            "plan_id": f"FP-{delivery_id}",
            "origin": {"lat": 37.7749, "lon": -122.4194, "altitude_m": 0},
            "destination": {"lat": destination_lat, "lon": destination_lon, "altitude_m": 0},
            "waypoints": [
                {"lat": 37.7800, "lon": -122.4100, "altitude_m": 120},
                {"lat": 37.7850, "lon": -122.4000, "altitude_m": 120},
                {"lat": destination_lat, "lon": destination_lon, "altitude_m": 120},
            ],
            "distance_km": 8.5,
            "estimated_duration_min": 12,
            "no_fly_zones_avoided": ["SFO_AIRPORT", "MILITARY_BASE_1"],
            "weather_clear": True,
        }

        logger.info(f"   ✅ Flight path planned: {flight_plan['distance_km']} km, {flight_plan['estimated_duration_min']} min")
        return flight_plan

    @compensate("plan_flight_path")
    async def cancel_flight_plan(self, ctx: SagaContext) -> None:
        """Cancel flight plan and release airspace reservation."""
        delivery_id = ctx.get("delivery_id")
        logger.warning(f"🗺️  Canceling flight plan for delivery {delivery_id}")

        plan_id = ctx.get("plan_id")
        logger.info(f"   Canceling flight plan {plan_id}")
        logger.info("   Airspace slot released")

        await asyncio.sleep(0.05)

    @action("get_airspace_authorization", depends_on=["plan_flight_path"])
    async def get_airspace_authorization(self, ctx: SagaContext) -> dict[str, Any]:
        """Request FAA airspace authorization (LAANC/UAS)."""
        delivery_id = ctx.get("delivery_id")
        simulate_failure = ctx.get("simulate_failure", False)
        
        logger.info(f"✈️  Requesting airspace authorization for delivery {delivery_id}")
        await asyncio.sleep(0.25)

        if simulate_failure:
            raise SagaStepError(
                "Airspace authorization denied - temporary flight restriction (TFR) in effect"
            )

        # Simulate LAANC (Low Altitude Authorization and Notification Capability)
        authorization = {
            "authorization_id": f"AUTH-{delivery_id}",
            "authority": "FAA-LAANC",
            "status": "approved",
            "max_altitude_m": 122,  # 400 feet
            "valid_from": "2026-01-01T14:30:00Z",
            "valid_until": "2026-01-01T15:00:00Z",
            "flight_plan_id": ctx.get("plan_id"),
            "conditions": ["daylight_only", "visual_line_of_sight"],
        }

        logger.info(f"   ✅ Airspace authorized (ID: {authorization['authorization_id']})")
        return authorization

    @compensate("get_airspace_authorization")
    async def revoke_airspace_authorization(self, ctx: SagaContext) -> None:
        """Revoke airspace authorization with FAA."""
        delivery_id = ctx.get("delivery_id")
        logger.warning(f"✈️  Revoking airspace authorization for delivery {delivery_id}")

        authorization_id = ctx.get("authorization_id")
        logger.info(f"   Revoking authorization {authorization_id}")
        logger.info("   FAA notified of cancellation")

        await asyncio.sleep(0.1)

    @action("pickup_package", depends_on=["get_airspace_authorization"])
    async def pickup_package(self, ctx: SagaContext) -> dict[str, Any]:
        """Pick up package from warehouse using automated system."""
        package_id = ctx.get("package_id")
        warehouse_id = ctx.get("warehouse_id")
        package_weight_kg = ctx.get("package_weight_kg")
        
        logger.info(f"📦 Picking up package {package_id} from {warehouse_id}")
        await asyncio.sleep(0.15)

        # Simulate automated package loading
        pickup_result = {
            "package_id": package_id,
            "warehouse_id": warehouse_id,
            "drone_id": ctx.get("drone_id"),
            "weight_kg": package_weight_kg,
            "secured": True,
            "pickup_timestamp": "2026-01-01T14:35:00Z",
            "loading_bay": "BAY-3",
        }

        logger.info(f"   ✅ Package secured on {pickup_result['drone_id']}")
        return pickup_result

    @compensate("pickup_package")
    async def return_package_to_warehouse(self, ctx: SagaContext) -> None:
        """Return package to warehouse inventory."""
        package_id = ctx.get("package_id")
        logger.warning(f"📦 Returning package {package_id} to warehouse")

        warehouse_id = ctx.get("warehouse_id")
        loading_bay = ctx.get("loading_bay")

        logger.info(f"   Returning package to {warehouse_id} {loading_bay}")
        logger.info("   Package returned to inventory")

        await asyncio.sleep(0.1)

    @action("execute_delivery_flight", depends_on=["pickup_package"])
    async def execute_delivery_flight(self, ctx: SagaContext) -> dict[str, Any]:
        """Execute autonomous delivery flight to destination."""
        delivery_id = ctx.get("delivery_id")
        logger.info(f"🚁 Executing delivery flight for {delivery_id}")
        await asyncio.sleep(0.3)

        # Simulate flight execution with telemetry
        flight_result = {
            "delivery_id": delivery_id,
            "drone_id": ctx.get("drone_id"),
            "takeoff_time": "2026-01-01T14:35:00Z",
            "landing_time": "2026-01-01T14:47:00Z",
            "actual_duration_min": 12,
            "distance_flown_km": 8.5,
            "battery_used_percent": 18,
            "final_battery_level": 77,
            "weather_encountered": "clear",
            "incidents": [],
        }

        logger.info(
            f"   ✅ Flight completed: {flight_result['distance_flown_km']} km "
            f"(battery: {flight_result['final_battery_level']}%)"
        )
        return flight_result

    @compensate("execute_delivery_flight")
    async def initiate_drone_return(self, ctx: SagaContext) -> None:
        """Initiate emergency return to warehouse (if flight started)."""
        delivery_id = ctx.get("delivery_id")
        logger.warning(f"🚁 EMERGENCY: Initiating drone return for {delivery_id}")

        drone_id = ctx.get("drone_id")
        logger.info(f"   Drone {drone_id} returning to warehouse")
        logger.info("   Package will be returned to inventory")

        await asyncio.sleep(0.15)

    @action("confirm_delivery", depends_on=["execute_delivery_flight"])
    async def confirm_delivery(self, ctx: SagaContext) -> dict[str, Any]:
        """Confirm delivery with photo and customer signature."""
        delivery_id = ctx.get("delivery_id")
        package_id = ctx.get("package_id")
        
        logger.info(f"📸 Confirming delivery for {delivery_id}")
        await asyncio.sleep(0.15)

        # Simulate delivery confirmation
        confirmation = {
            "delivery_id": delivery_id,
            "package_id": package_id,
            "confirmed": True,
            "photo_id": f"PHOTO-{delivery_id}",
            "signature_id": f"SIG-{delivery_id}",
            "delivery_timestamp": "2026-01-01T14:47:30Z",
            "proof_of_delivery": "https://cdn.example.com/delivery-proof.jpg",
        }

        logger.info(f"   ✅ Delivery confirmed with photo proof")
        return confirmation

    @compensate("confirm_delivery")
    async def void_delivery_confirmation(self, ctx: SagaContext) -> None:
        """Void delivery confirmation (delivery must be reattempted)."""
        delivery_id = ctx.get("delivery_id")
        logger.warning(f"📸 Voiding delivery confirmation for {delivery_id}")

        logger.info(f"   Voiding confirmation for {delivery_id}")
        logger.info("   Delivery marked as FAILED - requires reattempt")

        await asyncio.sleep(0.05)

    @action("return_drone_to_base", depends_on=["confirm_delivery"])
    async def return_drone_to_base(self, ctx: SagaContext) -> dict[str, Any]:
        """Return drone to base after successful delivery (idempotent)."""
        delivery_id = ctx.get("delivery_id")
        logger.info(f"🏠 Returning drone to base for delivery {delivery_id}")
        await asyncio.sleep(0.2)

        # Simulate return flight
        return_result = {
            "drone_id": ctx.get("drone_id"),
            "return_flight_duration_min": 13,
            "final_battery_level": 60,
            "status": "available",
            "next_maintenance_hours": 15,
        }

        logger.info(
            f"   ✅ Drone returned (battery: {return_result['final_battery_level']}%, "
            f"status: {return_result['status']})"
        )
        return return_result


async def main():
    """Run the supply chain drone delivery saga demo."""
    print("=" * 80)
    print("Supply Chain Drone Delivery Saga Demo - Autonomous Delivery Orchestration")
    print("=" * 80)

    # Reusable saga instance
    saga = SupplyChainDroneDeliverySaga()

    # Scenario 1: Successful drone delivery
    print("\n🟢 Scenario 1: Successful Drone Delivery")
    print("-" * 80)

    success_data = {
        "delivery_id": "DEL-2026-001",
        "package_id": "PKG-54321",
        "warehouse_id": "WH-SF-01",
        "destination_lat": 37.7899,
        "destination_lon": -122.3999,
        "package_weight_kg": 2.5,
        "priority": "standard",
        "simulate_failure": False,
    }

    result_success = await saga.run(success_data)

    print(f"\n{'✅' if result_success.get('saga_id') else '❌'} Drone Delivery Result:")
    print(f"   Saga ID: {result_success.get('saga_id')}")
    print(f"   Delivery ID: {result_success.get('delivery_id')}")
    print(f"   Package: {success_data['package_id']} ({success_data['package_weight_kg']} kg)")
    print("   Status: Successfully delivered with photo proof")

    # Scenario 2: Airspace authorization denied with automatic rollback
    print("\n\n🔴 Scenario 2: Airspace Authorization Denied (TFR Active)")
    print("-" * 80)

    failure_data = {
        "delivery_id": "DEL-2026-002",
        "package_id": "PKG-98765",
        "warehouse_id": "WH-SF-01",
        "destination_lat": 37.7850,
        "destination_lon": -122.4050,
        "package_weight_kg": 1.8,
        "priority": "express",
        "simulate_failure": True,  # Simulate airspace authorization failure
    }

    try:
        result_failure = await saga.run(failure_data)
    except Exception:
        result_failure = {}

    print(f"\n{'❌' if not result_failure.get('saga_id') else '✅'} Rollback Result:")
    print(f"   Saga ID: {result_failure.get('saga_id', 'N/A')}")
    print(f"   Delivery ID: {failure_data['delivery_id']}")
    print(f"   Package: {failure_data['package_id']}")
    print("   Status: Failed - airspace authorization denied")
    print("   Actions: Drone released, flight plan canceled, package available for retry")

    print("\n" + "=" * 80)
    print("Key Features Demonstrated:")
    print("  ✅ Real-time airspace coordination (FAA LAANC)")
    print("  ✅ Battery and range management")
    print("  ✅ Weather condition checks")
    print("  ✅ Regulatory compliance (FAA Part 107)")
    print("  ✅ Automatic rerouting on failure")
    print("  ✅ Proof of delivery (photo + signature)")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
