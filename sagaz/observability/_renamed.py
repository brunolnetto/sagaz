"""Metrics renamed to ``sagaz_*`` (#572), still emitted under their old names until 3.0.

Before 2.6.0 the outbox, the consumer inbox and ``PrometheusMetrics`` named their
metrics ``outbox_*``, ``consumer_inbox_*`` and ``saga_*``; the rest of the library used
``sagaz_*``. Every metric is now ``sagaz_*``.

So that dashboards and alerts written for the old names keep working during the
transition, a renamed metric is recorded under both names while
``SAGAZ_METRICS_OLD_NAMES`` is on, which is the default. Set it to ``0`` once your
dashboards use the new names; 3.0 removes the old names and this setting.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar, cast

#: Environment variable that turns the old metric names off (``0``, ``false``, ``no``).
OLD_NAMES_ENV = "SAGAZ_METRICS_OLD_NAMES"

M = TypeVar("M")


def emit_old_names() -> bool:
    """Whether renamed metrics are also recorded under their old names."""
    return os.environ.get(OLD_NAMES_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


class Both:
    """Records each call on a metric under its new name and its old one."""

    def __init__(self, new: object, old: object) -> None:
        # prometheus_client's metric classes, or their labelled children.
        self._new: Any = new
        self._old: Any = old

    def labels(self, *args: Any, **kwargs: Any) -> Both:
        return Both(self._new.labels(*args, **kwargs), self._old.labels(*args, **kwargs))

    def inc(self, amount: float = 1) -> None:
        self._new.inc(amount)
        self._old.inc(amount)

    def dec(self, amount: float = 1) -> None:
        self._new.dec(amount)
        self._old.dec(amount)

    def set(self, value: float) -> None:
        self._new.set(value)
        self._old.set(value)

    def observe(self, amount: float) -> None:
        self._new.observe(amount)
        self._old.observe(amount)

    @contextmanager
    def time(self) -> Iterator[None]:
        """Observe the block's duration, in seconds, under both names."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.observe(time.perf_counter() - start)


def renamed(
    metric_class: Callable[..., M],
    name: str,
    old_name: str,
    documentation: str,
    *args: Any,
    **kwargs: Any,
) -> M:
    """``metric_class(name, documentation, ...)``, also recorded as *old_name* if enabled.

    The returned object accepts the calls the library makes on a metric (``labels``,
    ``inc``, ``dec``, ``set``, ``observe``, ``time``), so call sites do not change.
    """
    new = metric_class(name, documentation, *args, **kwargs)
    if not emit_old_names():
        return new
    old = metric_class(
        old_name, f"{documentation} (old name, removed in 3.0: use {name})", *args, **kwargs
    )
    # Both stands in for the metric: it implements every method the library calls on it.
    return cast("M", Both(new, old))
