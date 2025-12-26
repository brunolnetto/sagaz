# ============================================
# FILE: saga/monitoring/metrics.py
# ============================================

"""
Metrics collection for sagas
"""

from typing import Any

from sagaz import SagaStatus


class SagaMetrics:
    """Collect and expose saga metrics"""

    def __init__(self):
        self.metrics = {
            "total_executed": 0,
            "total_successful": 0,
            "total_failed": 0,
            "total_rolled_back": 0,
            "average_execution_time": 0.0,
            "by_saga_name": {},
        }

    def record_execution(self, saga_name: str, status: SagaStatus, duration: float):
        """Record saga execution"""
        self.metrics["total_executed"] += 1
        self._increment_status_counter(status)
        self._update_average_time(duration)
        self._update_saga_stats(saga_name, status)

    def _increment_status_counter(self, status: SagaStatus) -> None:
        """Increment the appropriate status counter."""
        status_map = {
            SagaStatus.COMPLETED: "total_successful",
            SagaStatus.FAILED: "total_failed",
            SagaStatus.ROLLED_BACK: "total_rolled_back",
        }
        counter = status_map.get(status)
        if counter:
            self.metrics[counter] += 1

    def _update_average_time(self, duration: float) -> None:
        """Update average execution time."""
        total_time = self.metrics["average_execution_time"] * (
            self.metrics["total_executed"] - 1
        )
        self.metrics["average_execution_time"] = (
            total_time + duration
        ) / self.metrics["total_executed"]

    def _update_saga_stats(self, saga_name: str, status: SagaStatus) -> None:
        """Update per-saga statistics."""
        if saga_name not in self.metrics["by_saga_name"]:
            self.metrics["by_saga_name"][saga_name] = {
                "count": 0,
                "success": 0,
                "failed": 0,
            }

        self.metrics["by_saga_name"][saga_name]["count"] += 1
        if status == SagaStatus.COMPLETED:
            self.metrics["by_saga_name"][saga_name]["success"] += 1
        else:
            self.metrics["by_saga_name"][saga_name]["failed"] += 1

    def get_metrics(self) -> dict[str, Any]:
        """Get all metrics"""
        success_rate = (
            self.metrics["total_successful"] / self.metrics["total_executed"] * 100
            if self.metrics["total_executed"] > 0
            else 0
        )

        return {
            **self.metrics,
            "success_rate": f"{success_rate:.2f}%",
        }
