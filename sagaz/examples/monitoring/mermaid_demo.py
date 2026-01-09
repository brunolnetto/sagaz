"""
Mermaid Visualization Demo for Sagaz.

This script demonstrates how to generate comprehensive Mermaid diagrams for complex sagas,
showcasing both successful executions and failure/compensation scenarios with
automatic trail highlighting.
"""

import asyncio
from datetime import datetime
from uuid import uuid4

from sagaz import Saga, action, compensate
from sagaz.storage.memory import InMemorySagaStorage
from sagaz.types import SagaStatus, SagaStepStatus

# -----------------------------------------------------------------------------
# 1. Define a Complex Saga (E-commerce Order)
# -----------------------------------------------------------------------------


class OrderSaga(Saga):
    saga_name = "order_processing"

    @action("validate_order")
    async def validate(self, ctx):
        return {"valid": True}

    @compensate("validate_order")
    async def undo_validate(self, ctx):
        pass

    @action("check_inventory", depends_on=["validate_order"])
    async def check_inventory(self, ctx):
        return {"inventory_checked": True}

    @compensate("check_inventory")
    async def release_inventory_check(self, ctx):
        pass

    @action("fraud_check", depends_on=["validate_order"])
    async def fraud_check(self, ctx):
        return {"fraud_score": 0}

    @compensate("fraud_check")
    async def undo_fraud_check(self, ctx):
        pass

    @action("reserve_inventory", depends_on=["check_inventory"])
    async def reserve_inventory(self, ctx):
        return {"reserved": True}

    @compensate("reserve_inventory")
    async def unreserve_inventory(self, ctx):
        pass

    @action("calculate_shipping", depends_on=["check_inventory"])
    async def calculate_shipping(self, ctx):
        return {"cost": 10.0}

    @action("process_payment", depends_on=["reserve_inventory", "fraud_check"])
    async def process_payment(self, ctx):
        # Simulate payment failure logic could be here
        return {"paid": True}

    @compensate("process_payment")
    async def refund_payment(self, ctx):
        pass

    @action("ship_order", depends_on=["process_payment", "calculate_shipping"])
    async def ship_order(self, ctx):
        return {"shipped": True}

    @compensate("ship_order")
    async def cancel_shipment(self, ctx):
        pass

    @action("send_confirmation", depends_on=["ship_order"])
    async def send_confirmation(self, ctx):
        return {"email_sent": True}


# -----------------------------------------------------------------------------
# 2. Helper to Simulate Execution Storage
# -----------------------------------------------------------------------------


async def seed_storage_with_scenario(storage: InMemorySagaStorage, saga_id: str, scenario: str):
    """
    Manually seed the memory storage with a saga execution state.
    This simulates fetching a real execution trace from DB.
    """

    all_steps = [
        "validate_order",
        "check_inventory",
        "fraud_check",
        "reserve_inventory",
        "calculate_shipping",
        "process_payment",
        "ship_order",
        "send_confirmation",
    ]

    steps_data = []
    saga_status = SagaStatus.PENDING

    if scenario == "success":
        saga_status = SagaStatus.COMPLETED
        for step_name in all_steps:
            steps_data.append(
                {
                    "name": step_name,
                    "status": SagaStepStatus.COMPLETED.value,
                    "result": None,
                    "error": None,
                    "executed_at": datetime.now().isoformat(),
                    "compensated_at": None,
                    "retry_count": 0,
                }
            )

    elif scenario == "failure":
        # Fails at process_payment, compensates previous steps
        saga_status = SagaStatus.ROLLED_BACK

        # Steps that ran successfully before failure
        completed = {
            "validate_order",
            "check_inventory",
            "fraud_check",
            "reserve_inventory",
            "calculate_shipping",
        }

        # Steps that were compensated (reverse order of dependency)
        compensated = {"reserve_inventory", "fraud_check", "check_inventory", "validate_order"}

        failed_step = "process_payment"

        for step_name in all_steps:
            status = "pending"  # default
            compensated_at = None

            if step_name in completed:
                status = "completed"
                if step_name in compensated:
                    status = "compensated"
                    compensated_at = datetime.now().isoformat()
            elif step_name == failed_step:
                status = "failed"

            if status != "pending":
                steps_data.append(
                    {
                        "name": step_name,
                        "status": status,
                        "result": None,
                        "error": None,
                        "executed_at": datetime.now().isoformat(),
                        "compensated_at": compensated_at,
                        "retry_count": 0,
                    }
                )

    # Save directly to storage
    await storage.save_saga_state(
        saga_id=saga_id,
        saga_name="order_processing",
        status=saga_status,
        steps=steps_data,
        context={},
        metadata={},
    )


# -----------------------------------------------------------------------------
# 3. Execution
# -----------------------------------------------------------------------------


async def main():
    saga = OrderSaga()
    storage = InMemorySagaStorage()


    # CASE 0: Overall Saga Structure (static diagram, no execution trail)
    diagram_overall = saga.to_mermaid()

    with open("saga_overall.mmd", "w", encoding="utf-8") as f:
        f.write(f"```mermaid\n{diagram_overall}\n```")

    # CASE 1: Successful Execution
    success_id = str(uuid4())
    await seed_storage_with_scenario(storage, success_id, "success")

    diagram_success = await saga.to_mermaid_with_execution(success_id, storage)

    with open("saga_success.mmd", "w", encoding="utf-8") as f:
        f.write(f"```mermaid\n{diagram_success}\n```")

    # CASE 2: Failed Execution with Compensation
    fail_id = str(uuid4())
    await seed_storage_with_scenario(storage, fail_id, "failure")

    diagram_fail = await saga.to_mermaid_with_execution(fail_id, storage)

    with open("saga_failure.mmd", "w", encoding="utf-8") as f:
        f.write(f"```mermaid\n{diagram_fail}\n```")

    # CASE 3: Success with Duration Display (manual highlight_trail)
    diagram_with_duration = saga.to_mermaid(
        highlight_trail={
            "completed_steps": [
                "validate_order",
                "check_inventory",
                "fraud_check",
                "reserve_inventory",
                "calculate_shipping",
                "process_payment",
                "ship_order",
                "send_confirmation",
            ],
            "step_durations": {
                "validate_order": "45ms",
                "check_inventory": "120ms",
                "fraud_check": "230ms",
                "reserve_inventory": "85ms",
                "calculate_shipping": "65ms",
                "process_payment": "450ms",
                "ship_order": "180ms",
                "send_confirmation": "30ms",
            },
            "total_duration": "1.2s",
        }
    )

    with open("saga_success_with_duration.mmd", "w", encoding="utf-8") as f:
        f.write(f"```mermaid\n{diagram_with_duration}\n```")

    # CASE 4: Failure with Duration Display including compensation times
    diagram_fail_with_duration = saga.to_mermaid(
        highlight_trail={
            "completed_steps": [
                "validate_order",
                "check_inventory",
                "fraud_check",
                "reserve_inventory",
                "calculate_shipping",
            ],
            "failed_step": "process_payment",
            "compensated_steps": [
                "validate_order",
                "check_inventory",
                "fraud_check",
                "reserve_inventory",
            ],
            "step_durations": {
                "validate_order": "45ms",
                "check_inventory": "120ms",
                "fraud_check": "230ms",
                "reserve_inventory": "85ms",
                "calculate_shipping": "65ms",
                "process_payment": "150ms",  # Failed after 150ms
            },
            "comp_durations": {
                "reserve_inventory": "40ms",
                "fraud_check": "25ms",
                "check_inventory": "60ms",
                "validate_order": "15ms",
            },
            "total_duration": "980ms",
        }
    )

    with open("saga_failure_with_duration.mmd", "w", encoding="utf-8") as f:
        f.write(f"```mermaid\n{diagram_fail_with_duration}\n```")



if __name__ == "__main__":
    asyncio.run(main())
