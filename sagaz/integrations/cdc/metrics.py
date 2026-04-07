"""
CDCMetrics — in-process Prometheus-compatible counters for CDC monitoring.

Tracks:
  - ``sagaz_cdc_events_total``    — total CDC events processed
  - ``sagaz_cdc_errors_total``    — total processing errors
  - ``sagaz_cdc_lag_seconds``     — rolling mean of source-to-process lag
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CDCMetrics:
    """
    Lightweight in-process metrics for CDC workers.

    Use ``snapshot()`` to export a dict compatible with Prometheus exposition.
    """

    _events_total: int = field(default=0, init=False)
    _errors_total: int = field(default=0, init=False)
    _lag_sum_ms: float = field(default=0.0, init=False)
    _lag_count: int = field(default=0, init=False)

    def record_event(self, lag_ms: float = 0.0) -> None:
        """Record a successfully processed event with optional *lag_ms*."""
        self._events_total += 1
        if lag_ms > 0:
            self._lag_sum_ms += lag_ms
            self._lag_count += 1

    def increment_error(self) -> None:
        """Record a processing error."""
        self._errors_total += 1

    @property
    def events_total(self) -> int:
        return self._events_total

    @property
    def errors_total(self) -> int:
        return self._errors_total

    @property
    def mean_lag_seconds(self) -> float:
        if self._lag_count == 0:
            return 0.0
        return (self._lag_sum_ms / self._lag_count) / 1000.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "sagaz_cdc_events_total": self._events_total,
            "sagaz_cdc_errors_total": self._errors_total,
            "sagaz_cdc_lag_seconds": self.mean_lag_seconds,
        }

    def reset(self) -> None:
        self._events_total = 0
        self._errors_total = 0
        self._lag_sum_ms = 0.0
        self._lag_count = 0
