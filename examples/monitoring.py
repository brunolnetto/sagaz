"""
Real-world usage examples for the production-ready Saga Pattern implementation

This demonstrates:
1. E-commerce order processing saga
2. Payment processing with multiple providers
3. Multi-service booking system
4. Database migration saga
5. Monitoring and observability integration
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from sagaz import (
    ClassicSaga,
    SagaContext,
    SagaOrchestrator,
    SagaResult,
    SagaStatus,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)



# ============================================
# MONITORING & OBSERVABILITY
# ============================================


class MonitoredSagaOrchestrator(SagaOrchestrator):
    """
    Enhanced orchestrator with monitoring and metrics
    """

    def __init__(self):
        super().__init__()
        self.metrics = {
            "total_executed": 0,
            "total_successful": 0,
            "total_failed": 0,
            "total_rolled_back": 0,
            "average_execution_time": 0.0,
        }

    async def execute_saga(self, saga: ClassicSaga) -> SagaResult:
        """Execute saga with metrics collection"""
        start_time = datetime.now()

        result = await super().execute_saga(saga)

        # Update metrics
        self.metrics["total_executed"] += 1

        if result.status == SagaStatus.COMPLETED:
            self.metrics["total_successful"] += 1
        elif result.status == SagaStatus.FAILED:
            self.metrics["total_failed"] += 1
        elif result.status == SagaStatus.ROLLED_BACK:
            self.metrics["total_rolled_back"] += 1

        # Update average execution time
        total_time = self.metrics["average_execution_time"] * (
            self.metrics["total_executed"] - 1
        )
        self.metrics["average_execution_time"] = (total_time + result.execution_time) / self.metrics[
            "total_executed"
        ]

        logger.info(
            f"Saga {saga.name} completed in {result.execution_time:.2f}s - "
            f"Status: {result.status.value}"
        )

        return result

    def get_metrics(self) -> dict[str, Any]:
        """Get orchestrator metrics"""
        success_rate = (
            (self.metrics["total_successful"] / self.metrics["total_executed"] * 100)
            if self.metrics["total_executed"] > 0
            else 0
        )

        return {
            **self.metrics,
            "success_rate": f"{success_rate:.2f}%",
        }


# ============================================
# DEMO RUNNER
# ============================================
async def demo_failure_with_rollback():
    """Demo: Saga failure with successful rollback"""
    print("\n" + "=" * 60)
    print("DEMO 3: Saga Failure with Rollback")
    print("=" * 60)

    orchestrator = MonitoredSagaOrchestrator()

    # Create a saga that will fail
    class FailingSaga(ClassicSaga):
        async def build(self):
            await self.add_step(
                "step1",
                lambda ctx: asyncio.sleep(0.1) or "step1_success",
                lambda r, ctx: logger.info("Compensating step1"),
            )
            await self.add_step(
                "step2",
                lambda ctx: asyncio.sleep(0.1) or "step2_success",
                lambda r, ctx: logger.info("Compensating step2"),
            )
            await self.add_step(
                "failing_step",
                lambda ctx: (_ for _ in ()).throw(ValueError("Intentional failure")),
                max_retries=1,
            )

    saga = FailingSaga(name="FailureDemo")
    await saga.build()

    # Execute saga
    result = await orchestrator.execute_saga(saga)

    # Print result
    print(f"\n❌ Saga Result (Expected Failure):")
    print(f"   Success: {result.success}")
    print(f"   Status: {result.status.value}")
    print(f"   Completed Steps: {result.completed_steps}/{result.total_steps}")
    print(f"   Error: {result.error}")
    print(f"   Compensation Errors: {len(result.compensation_errors)}")

    print("\n💡 Notice: Steps 1 and 2 were successfully compensated (rolled back)")


async def main():
    """Run all demos"""
    await demo_failure_with_rollback()

    print("\n" + "=" * 60)
    print("All demos completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())