"""
Smart Grid Energy Management Saga Example

Demonstrates demand response event for grid stabilization with real-time
grid balancing, distributed energy resource coordination, and incentive payments.
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


class SmartGridEnergySaga(Saga):
    """
    Demand response event orchestration for grid stabilization.
    
    This saga is stateless - all data is passed through the context via the run() method.
    
    Expected context:
        - event_id: str
        - grid_operator_id: str
        - target_reduction_mw: float
        - event_duration_hours: int
        - incentive_rate_per_kwh: float
        - simulate_failure: bool (optional)
    """

    saga_name = "smart-grid-energy-management"

    @action("forecast_demand")
    async def forecast_demand(self, ctx: SagaContext) -> dict[str, Any]:
        """Forecast energy demand for the event period."""
        event_id = ctx.get("event_id")
        event_duration_hours = ctx.get("event_duration_hours", 4)
        
        logger.info(f"📊 Forecasting energy demand for event {event_id}")
        await asyncio.sleep(0.15)

        # Simulate ML-based demand forecasting
        forecast = {
            "event_id": event_id,
            "forecast_method": "LSTM Neural Network",
            "baseline_demand_mw": 1250.5,
            "predicted_peak_mw": 1425.0,
            "confidence_level": 0.92,
            "weather_factors": {
                "temperature_f": 98,
                "humidity_percent": 75,
                "heat_index": "extreme",
            },
            "time_period": f"{event_duration_hours} hours",
        }

        logger.info(
            f"   ✅ Forecast: Baseline {forecast['baseline_demand_mw']} MW, "
            f"Peak {forecast['predicted_peak_mw']} MW"
        )
        return forecast

    @compensate("forecast_demand")
    async def log_forecast_cancellation(self, ctx: SagaContext) -> None:
        """Log forecast cancellation for audit trail."""
        event_id = ctx.get("event_id")
        logger.warning(f"📊 Logging forecast cancellation for event {event_id}")

        logger.info(f"   Audit: Forecast {event_id} canceled")

        await asyncio.sleep(0.05)

    @action("identify_participants", depends_on=["forecast_demand"])
    async def identify_participants(self, ctx: SagaContext) -> dict[str, Any]:
        """Identify participating buildings and DERs (Distributed Energy Resources)."""
        event_id = ctx.get("event_id")
        logger.info(f"🏢 Identifying demand response participants for event {event_id}")
        await asyncio.sleep(0.2)

        # Simulate participant selection algorithm
        participants = {
            "commercial_buildings": [
                {
                    "building_id": f"BLDG-{i}",
                    "type": "office" if i % 2 == 0 else "retail",
                    "baseline_kw": 150 + (i * 10),
                    "reduction_potential_kw": 30 + (i * 2),
                    "location": f"Zone-{(i % 5) + 1}",
                }
                for i in range(1, 21)
            ],
            "industrial_facilities": [
                {
                    "facility_id": f"FAC-{i}",
                    "type": "manufacturing",
                    "baseline_kw": 500 + (i * 50),
                    "reduction_potential_kw": 100 + (i * 10),
                }
                for i in range(1, 6)
            ],
            "battery_storage": [
                {
                    "battery_id": f"BESS-{i}",
                    "capacity_kwh": 1000,
                    "discharge_rate_kw": 250,
                    "current_soc_percent": 85,
                }
                for i in range(1, 4)
            ],
            "total_participants": 28,
            "total_reduction_potential_mw": 2.15,
        }

        logger.info(
            f"   ✅ Identified {participants['total_participants']} participants "
            f"({participants['total_reduction_potential_mw']} MW potential)"
        )
        return participants

    @compensate("identify_participants")
    async def notify_participants_cancellation(self, ctx: SagaContext) -> None:
        """Notify participants that demand response event is canceled."""
        logger.warning(f"🏢 Notifying participants of event cancellation")

        total_participants = ctx.get("total_participants", 0)
        logger.info(f"   Sending cancellation to {total_participants} participants")

        await asyncio.sleep(0.1)

    @action("send_reduction_requests", depends_on=["identify_participants"])
    async def send_reduction_requests(self, ctx: SagaContext) -> dict[str, Any]:
        """Send demand reduction requests to all participants."""
        event_id = ctx.get("event_id")
        target_reduction_mw = ctx.get("target_reduction_mw")
        event_duration_hours = ctx.get("event_duration_hours")
        simulate_failure = ctx.get("simulate_failure", False)
        
        logger.info(f"📨 Sending reduction requests for event {event_id}")
        await asyncio.sleep(0.2)

        if simulate_failure:
            raise SagaStepError("Communication failure with demand response management system")

        # Simulate sending requests via OpenADR (Open Automated Demand Response)
        request_result = {
            "event_id": event_id,
            "protocol": "OpenADR 2.0b",
            "requests_sent": ctx.get("total_participants", 28),
            "acknowledgments_received": 26,
            "opt_outs": 2,
            "target_reduction_mw": target_reduction_mw,
            "event_start": "2026-01-01T15:00:00Z",
            "event_end": f"2026-01-01T{15 + event_duration_hours}:00:00Z",
        }

        logger.info(
            f"   ✅ Sent {request_result['requests_sent']} requests, "
            f"{request_result['acknowledgments_received']} acknowledged"
        )
        return request_result

    @compensate("send_reduction_requests")
    async def send_cancellation_requests(self, ctx: SagaContext) -> None:
        """Send cancellation requests to all participants."""
        event_id = ctx.get("event_id")
        logger.warning(f"📨 Sending cancellation requests for event {event_id}")

        requests_sent = ctx.get("requests_sent", 0)
        logger.info(f"   Sending cancellations to {requests_sent} participants")
        logger.info("   Participants can resume normal operations")

        await asyncio.sleep(0.15)

    @action("monitor_consumption", depends_on=["send_reduction_requests"])
    async def monitor_consumption(self, ctx: SagaContext) -> dict[str, Any]:
        """Monitor real-time energy consumption during event."""
        event_id = ctx.get("event_id")
        target_reduction_mw = ctx.get("target_reduction_mw", 0)
        event_duration_hours = ctx.get("event_duration_hours", 4)
        
        logger.info(f"📡 Monitoring real-time consumption for event {event_id}")
        await asyncio.sleep(0.25)

        # Simulate real-time monitoring via smart meters
        monitoring_result = {
            "event_id": event_id,
            "monitoring_interval_sec": 15,
            "total_samples": 240 * event_duration_hours,
            "actual_reduction_mw": target_reduction_mw * 0.87,  # 87% of target
            "baseline_consumption_mw": 1250.5,
            "event_consumption_mw": 1141.3,
            "participant_compliance": {
                "full_compliance": 20,
                "partial_compliance": 6,
                "non_compliance": 2,
            },
        }

        logger.info(
            f"   ✅ Monitored: {monitoring_result['actual_reduction_mw']:.2f} MW reduction "
            f"({(monitoring_result['actual_reduction_mw']/target_reduction_mw)*100:.1f}% of target)"
        )
        return monitoring_result

    @compensate("monitor_consumption")
    async def stop_monitoring(self, ctx: SagaContext) -> None:
        """Stop consumption monitoring and save data."""
        event_id = ctx.get("event_id")
        logger.warning(f"📡 Stopping consumption monitoring for event {event_id}")

        logger.info(f"   Monitoring stopped for {event_id}")
        logger.info("   Data saved for analysis")

        await asyncio.sleep(0.1)

    @action("verify_targets", depends_on=["monitor_consumption"])
    async def verify_targets(self, ctx: SagaContext) -> dict[str, Any]:
        """Verify that reduction targets were met."""
        event_id = ctx.get("event_id")
        target_reduction_mw = ctx.get("target_reduction_mw", 0)
        
        logger.info(f"✅ Verifying reduction targets for event {event_id}")
        await asyncio.sleep(0.1)

        actual_reduction_mw = ctx.get("actual_reduction_mw", 0)
        target_met = actual_reduction_mw >= (target_reduction_mw * 0.85)  # 85% threshold

        verification = {
            "event_id": event_id,
            "target_reduction_mw": target_reduction_mw,
            "actual_reduction_mw": actual_reduction_mw,
            "target_met": target_met,
            "achievement_percent": (actual_reduction_mw / target_reduction_mw) * 100,
            "grid_stability_maintained": True,
        }

        logger.info(
            f"   ✅ Verification: {'TARGET MET' if target_met else 'TARGET MISSED'} "
            f"({verification['achievement_percent']:.1f}%)"
        )
        return verification

    @compensate("verify_targets")
    async def log_verification_failure(self, ctx: SagaContext) -> None:
        """Log verification failure for audit."""
        event_id = ctx.get("event_id")
        logger.warning(f"✅ Logging verification rollback for event {event_id}")

        logger.info(f"   Audit: Verification {event_id} rolled back")

        await asyncio.sleep(0.05)

    @action("calculate_incentives", depends_on=["verify_targets"])
    async def calculate_incentives(self, ctx: SagaContext) -> dict[str, Any]:
        """Calculate incentive payments for participants."""
        event_id = ctx.get("event_id")
        event_duration_hours = ctx.get("event_duration_hours", 4)
        incentive_rate_per_kwh = ctx.get("incentive_rate_per_kwh", 0)
        
        logger.info(f"💰 Calculating incentive payments for event {event_id}")
        await asyncio.sleep(0.15)

        actual_reduction_mw = ctx.get("actual_reduction_mw", 0)
        total_kwh_reduced = actual_reduction_mw * 1000 * event_duration_hours

        # Simulate incentive calculation
        incentive_payments = {
            "event_id": event_id,
            "total_kwh_reduced": total_kwh_reduced,
            "incentive_rate_per_kwh": incentive_rate_per_kwh,
            "total_payment_usd": total_kwh_reduced * incentive_rate_per_kwh,
            "participant_payments": [
                {
                    "participant_id": f"PART-{i}",
                    "reduction_kwh": (total_kwh_reduced / 26) * 0.95,  # Vary by participant
                    "payment_usd": ((total_kwh_reduced / 26) * 0.95) * incentive_rate_per_kwh,
                }
                for i in range(1, 27)
            ],
        }

        logger.info(
            f"   ✅ Total incentives: ${incentive_payments['total_payment_usd']:,.2f} "
            f"for {len(incentive_payments['participant_payments'])} participants"
        )
        return incentive_payments

    @compensate("calculate_incentives")
    async def void_incentive_calculations(self, ctx: SagaContext) -> None:
        """Void incentive calculations (event canceled)."""
        event_id = ctx.get("event_id")
        logger.warning(f"💰 Voiding incentive calculations for event {event_id}")

        logger.info(f"   Voiding payments for {event_id}")
        logger.info("   No participant payments will be issued")

        await asyncio.sleep(0.05)

    @action("settle_with_grid_operator", depends_on=["calculate_incentives"])
    async def settle_with_grid_operator(self, ctx: SagaContext) -> dict[str, Any]:
        """Settle financial transactions with grid operator (idempotent)."""
        event_id = ctx.get("event_id")
        grid_operator_id = ctx.get("grid_operator_id")
        
        logger.info(f"🏦 Settling with grid operator for event {event_id}")
        await asyncio.sleep(0.15)

        total_payment = ctx.get("total_payment_usd", 0)

        settlement = {
            "event_id": event_id,
            "grid_operator_id": grid_operator_id,
            "settlement_amount_usd": total_payment,
            "settlement_timestamp": "2026-01-01T19:00:00Z",
            "payment_method": "ACH Transfer",
            "confirmation_id": f"SETTLE-{event_id}",
        }

        logger.info(f"   ✅ Settlement complete: ${settlement['settlement_amount_usd']:,.2f}")
        return settlement


async def main():
    """Run the smart grid energy management saga demo."""
    print("=" * 80)
    print("Smart Grid Energy Management Saga Demo - Demand Response Event")
    print("=" * 80)

    # Reusable saga instance
    saga = SmartGridEnergySaga()

    # Scenario 1: Successful demand response event
    print("\n🟢 Scenario 1: Successful Demand Response Event")
    print("-" * 80)

    success_data = {
        "event_id": "DR-2026-HEATWAVE-001",
        "grid_operator_id": "GRID-CAISO",
        "target_reduction_mw": 1.5,
        "event_duration_hours": 4,
        "incentive_rate_per_kwh": 0.15,
        "simulate_failure": False,
    }

    result_success = await saga.run(success_data)

    print(f"\n{'✅' if result_success.get('saga_id') else '❌'} Demand Response Result:")
    print(f"   Saga ID: {result_success.get('saga_id')}")
    print(f"   Event ID: {result_success.get('event_id')}")
    print(f"   Target Reduction: {success_data['target_reduction_mw']} MW")
    print(f"   Duration: {success_data['event_duration_hours']} hours")
    print("   Status: Grid stabilized, participants compensated")

    # Scenario 2: Communication failure with automatic rollback
    print("\n\n🔴 Scenario 2: Communication Failure with Demand Response System")
    print("-" * 80)

    failure_data = {
        "event_id": "DR-2026-HEATWAVE-002",
        "grid_operator_id": "GRID-CAISO",
        "target_reduction_mw": 2.0,
        "event_duration_hours": 3,
        "incentive_rate_per_kwh": 0.18,
        "simulate_failure": True,  # Simulate communication failure
    }

    try:
        result_failure = await saga.run(failure_data)
    except Exception:
        result_failure = {}

    print(f"\n{'❌' if not result_failure.get('saga_id') else '✅'} Rollback Result:")
    print(f"   Saga ID: {result_failure.get('saga_id', 'N/A')}")
    print(f"   Event ID: {failure_data['event_id']}")
    print("   Status: Failed - all participants notified of cancellation")
    print("   Actions: Monitoring stopped, no payments issued")

    print("\n" + "=" * 80)
    print("Key Features Demonstrated:")
    print("  ✅ Real-time grid balancing and load forecasting")
    print("  ✅ Distributed energy resource coordination (28 participants)")
    print("  ✅ OpenADR 2.0b protocol communication")
    print("  ✅ Smart meter monitoring (15-second intervals)")
    print("  ✅ Automatic incentive calculation and payment")
    print("  ✅ Grid operator settlement")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
