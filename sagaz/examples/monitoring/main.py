"""
Monitoring demo for saga orchestration.

Demonstrates how to collect metrics and monitor saga executions.
"""

import asyncio
import logging
import random
from datetime import datetime
from typing import Any

from sagaz import Saga, SagaContext, action, compensate
from sagaz.exceptions import SagaStepError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class MonitoredSagaOrchestrator:
    """
    Saga orchestrator with built-in metrics collection.

    Tracks success/failure rates and execution times for all sagas.
    """

    def __init__(self):
        self.sagas: dict[str, Saga] = {}
        self.metrics: dict[str, Any] = {
            "total_executed": 0,
            "total_successful": 0,
            "total_failed": 0,
            "total_rolled_back": 0,
            "execution_times": [],
        }

    async def execute_saga(self, saga: Saga, input_data: dict[str, Any]):
        """Execute a saga and collect metrics."""
        start_time = datetime.now()

        try:
            result = await saga.run(input_data)

            # Update metrics
            self.metrics["total_executed"] += 1
            self.metrics["total_successful"] += 1

            # Track execution time
            execution_time = (datetime.now() - start_time).total_seconds()
            self.metrics["execution_times"].append(execution_time)

            # Store saga
            self.sagas[saga._saga_id] = saga

            return result

        except Exception:
            # Track failure
            self.metrics["total_executed"] += 1
            self.metrics["total_failed"] += 1

            # Track execution time
            execution_time = (datetime.now() - start_time).total_seconds()
            self.metrics["execution_times"].append(execution_time)

            # Still store saga
            self.sagas[saga._saga_id] = saga

            # Re-raise to maintain saga behavior
            raise

    def get_metrics(self):
        """Get current metrics."""
        total = self.metrics["total_executed"]

        # Calculate average execution time
        avg_time = 0.0
        if self.metrics["execution_times"]:
            avg_time = sum(self.metrics["execution_times"]) / len(self.metrics["execution_times"])

        # Calculate success rate
        success_rate = "0.00%"
        if total > 0:
            rate = (self.metrics["total_successful"] / total) * 100
            success_rate = f"{rate:.2f}%"

        return {
            "total_executed": total,
            "total_successful": self.metrics["total_successful"],
            "total_failed": self.metrics["total_failed"],
            "total_rolled_back": self.metrics["total_rolled_back"],
            "success_rate": success_rate,
            "average_execution_time": f"{avg_time:.4f}s",
        }


class SimulatedOperationSaga(Saga):
    """A saga that simulates operations for monitoring demo."""
    
    saga_name = "simulated-operation"

    @action("step_a")
    async def step_a(self, ctx: SagaContext) -> dict[str, Any]:
        """First step."""
        logger.info("Executing Step A")
        await asyncio.sleep(random.uniform(0.01, 0.05))
        return {"step_a": "complete"}

    @compensate("step_a")
    async def undo_step_a(self, ctx: SagaContext) -> None:
        logger.warning("Compensating Step A")

    @action("step_b", depends_on=["step_a"])
    async def step_b(self, ctx: SagaContext) -> dict[str, Any]:
        """Second step, may fail based on input."""
        should_fail = ctx.get("simulate_failure", False)
        logger.info(f"Executing Step B (fail={should_fail})")
        await asyncio.sleep(random.uniform(0.01, 0.05))
        
        if should_fail:
            raise SagaStepError("Simulated failure in Step B")
            
        return {"step_b": "complete"}

    @compensate("step_b")
    async def undo_step_b(self, ctx: SagaContext) -> None:
        logger.warning("Compensating Step B")


async def main():
    print("=" * 60)
    print("📊 Saga Monitoring & Metrics Demo")
    print("=" * 60)

    orchestrator = MonitoredSagaOrchestrator()
    
    # 1. Run successful sagas
    print("\n--- Running Successful Sagas ---")
    for i in range(5):
        saga = SimulatedOperationSaga()
        try:
            await orchestrator.execute_saga(saga, {"id": i, "simulate_failure": False})
            print(f"✅ Saga {i} completed")
        except Exception as e:
            print(f"❌ Saga {i} failed: {e}")

    # 2. Run failing sagas
    print("\n--- Running Failing Sagas ---")
    for i in range(2):
        saga = SimulatedOperationSaga()
        try:
            await orchestrator.execute_saga(saga, {"id": i+5, "simulate_failure": True})
            print(f"✅ Saga {i+5} completed")
        except Exception as e:
            print(f"❌ Saga {i+5} failed as expected: {e}")

    # 3. Report Metrics
    print("\n" + "=" * 60)
    print("📈 Final Metrics Report")
    print("=" * 60)
    
    metrics = orchestrator.get_metrics()
    for key, value in metrics.items():
        print(f"{key.replace('_', ' ').title():<25}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
