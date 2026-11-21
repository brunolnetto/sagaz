"""``Counter`` and ``Histogram``: prometheus_client's, or no-op stand-ins without it.

The outbox records metrics when ``prometheus_client`` is installed and works the same
without it. Modules import the two names from here, so there is one stand-in.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


class NoOpMetric:
    """Accepts what a Prometheus counter or histogram accepts, and records nothing."""

    def inc(self, *args: Any, **kwargs: Any) -> None:
        """Do nothing."""

    def observe(self, *args: Any, **kwargs: Any) -> None:
        """Do nothing."""

    def labels(self, *args: Any, **kwargs: Any) -> NoOpMetric:
        return self

    @contextmanager
    def time(self) -> Iterator[None]:
        """A timing context that measures nothing."""
        yield


def _noop_metric(*args: Any, **kwargs: Any) -> NoOpMetric:
    return NoOpMetric()


# mypy reads the import alone: no ignore is needed with or without the dependency.
if TYPE_CHECKING:
    from prometheus_client import Counter, Histogram

    PROMETHEUS_AVAILABLE = True
else:
    try:
        from prometheus_client import Counter, Histogram

        PROMETHEUS_AVAILABLE = True
    except ImportError:
        PROMETHEUS_AVAILABLE = False
        Counter = Histogram = _noop_metric

__all__ = ["PROMETHEUS_AVAILABLE", "Counter", "Histogram", "NoOpMetric"]
