"""
Monitoring demo for saga orchestration.

Demonstrates how to collect metrics and monitor saga executions.
"""

import logging
from datetime import datetime

from sagaz import Saga

logger = logging.getLogger(__name__)


class MonitoredSagaOrchestrator:
    """
    Saga orchestrator with built-in metrics collection.

    Tracks success/failure rates and execution times for all sagas.
    """

    def __init__(self):
        self.sagas = {}
        self.metrics = {
            "total_executed": 0,
            "total_successful": 0,
            "total_failed": 0,
            "total_rolled_back": 0,
            "execution_times": [],
        }

    async def execute_saga(self, saga: Saga):
        """Execute a saga and collect metrics."""
        start_time = datetime.now()

        try:
            result = await saga.run({})

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
            "average_execution_time": avg_time,
        }

    def success_rate(self):
        """Calculate success rate as a float."""
        total = self.metrics["total_executed"]
        if total == 0:
            return 0.0
        return self.metrics["total_successful"] / total


async def demo_failure_with_rollback():
    """
    Demo showing saga failure and rollback.

    This is a placeholder function for demonstration purposes.
    In a real implementation, you would create a saga that demonstrates
    failure and compensation.
    """
    logger.info("Running demo failure with rollback")

    # Placeholder - would create and execute a saga that fails
    # and demonstrates compensation in action
