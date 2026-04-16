"""
Tests to cover prometheus ImportError fallback code in:
- sagaz/core/outbox/optimistic_publisher.py (lines 16-43)
- sagaz/core/outbox/consumer_inbox.py (lines 17-38)

Strategy: temporarily remove prometheus_client from sys.modules,
reload the target module, verify NoOp fallback behavior, then restore.
"""

import importlib
import sys
from contextlib import contextmanager

# Canonical module paths (post Phase-2 restructuring)
_ALIAS_TO_CANONICAL = {
    "sagaz.core.outbox.optimistic_publisher": "sagaz.core.outbox.optimistic_publisher",
    "sagaz.core.outbox.consumer_inbox": "sagaz.core.outbox.consumer_inbox",
}


@contextmanager
def _without_prometheus(module_name: str):
    """Context manager that reloads a module without prometheus_client available."""
    canonical = _ALIAS_TO_CANONICAL.get(module_name, module_name)
    # Save original modules (alias + canonical)
    orig_module = sys.modules.get(module_name)
    orig_canonical = sys.modules.get(canonical)
    orig_prometheus_modules = {k: v for k, v in sys.modules.items() if "prometheus_client" in k}

    # Remove prometheus from sys.modules
    for key in list(sys.modules.keys()):
        if "prometheus_client" in key:
            sys.modules.pop(key)
    # Block import
    sys.modules["prometheus_client"] = None  # type: ignore[assignment]

    # Force reload of both alias and canonical so the module re-evaluates the
    # try/except ImportError block at module level.
    sys.modules.pop(module_name, None)
    sys.modules.pop(canonical, None)

    try:
        mod = importlib.import_module(canonical)
        yield mod
    finally:
        # Remove the None sentinel
        if sys.modules.get("prometheus_client") is None:
            del sys.modules["prometheus_client"]

        # Restore prometheus modules
        for key, val in orig_prometheus_modules.items():
            sys.modules[key] = val

        # Remove reloaded modules and restore originals
        sys.modules.pop(module_name, None)
        sys.modules.pop(canonical, None)
        if orig_module is not None:
            sys.modules[module_name] = orig_module
        if orig_canonical is not None:
            sys.modules[canonical] = orig_canonical


class TestOptimisticPublisherPromethusFallback:
    """Cover lines 16-43 in optimistic_publisher.py."""

    def test_noop_metric_class_methods(self):
        """Verify NoOp fallback classes work when prometheus not available."""
        with _without_prometheus("sagaz.core.outbox.optimistic_publisher") as mod:
            assert not mod.PROMETHEUS_AVAILABLE

            # Counter and Histogram should be noops
            counter = mod.Counter("test_counter", "A test counter")
            counter.inc()  # Should work silently
            counter.inc(1)  # With amount
            counter.labels(reason="test").inc()  # With labels

            histogram = mod.Histogram("test_hist", "A test histogram")
            histogram.observe(0.5)  # Should work silently

            with histogram.time():  # Context manager
                pass  # Should not blow up

    def test_noop_metric_labels_returns_self(self):
        """Verify labels() returns self for chaining."""
        with _without_prometheus("sagaz.core.outbox.optimistic_publisher") as mod:
            assert not mod.PROMETHEUS_AVAILABLE

            counter = mod.Counter("c", "test")
            # labels() returns a _NoOpMetric
            labeled = counter.labels(reason="test")
            # Should be usable
            labeled.inc()

    def test_optimistic_publisher_works_with_noop(self):
        """Verify OptimisticPublisher can be instantiated and used with NoOp metrics."""
        from unittest.mock import AsyncMock

        with _without_prometheus("sagaz.core.outbox.optimistic_publisher") as mod:
            storage = AsyncMock()
            broker = AsyncMock()
            publisher = mod.OptimisticPublisher(storage=storage, broker=broker, enabled=True)
            assert publisher is not None
            assert not mod.PROMETHEUS_AVAILABLE


class TestConsumerInboxPrometheusFallback:
    """Cover lines 17-38 in consumer_inbox.py."""

    def test_noop_metric_class_methods(self):
        """Verify NoOp fallback classes work in consumer_inbox."""
        with _without_prometheus("sagaz.core.outbox.consumer_inbox") as mod:
            assert not mod.PROMETHEUS_AVAILABLE

            # Counter noop
            counter = mod.Counter("test_counter", "test", ["label1"])
            counter.inc()
            counter.labels(label1="foo").inc()

            # Histogram noop
            histogram = mod.Histogram("test_hist", "test", ["label1"])
            histogram.observe(1.0)
            histogram.labels(label1="bar").observe(0.1)

    def test_consumer_inbox_works_with_noop(self):
        """Verify ConsumerInbox can be instantiated with NoOp metrics."""
        with _without_prometheus("sagaz.core.outbox.consumer_inbox") as mod:
            from unittest.mock import AsyncMock

            storage = AsyncMock()
            inbox = mod.ConsumerInbox(storage=storage, consumer_name="test-consumer")
            assert inbox is not None
            assert not mod.PROMETHEUS_AVAILABLE

    def test_noop_counter_factory(self):
        """Verify _noop_counter returns a _NoOpMetric instance."""
        with _without_prometheus("sagaz.core.outbox.consumer_inbox") as mod:
            assert not mod.PROMETHEUS_AVAILABLE
            # Counter is the noop factory
            result = mod.Counter("name", "help")
            # No-op metric - calling inc/observe should not raise
            result.inc()
            result.observe(0.1)
            result.labels(consumer_name="c", event_type="e").inc()
