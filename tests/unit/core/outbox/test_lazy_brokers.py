"""Tests for the lazy optional-backend broker constructors."""

from unittest.mock import MagicMock

import pytest

from sagaz.core.outbox import brokers
from sagaz.core.outbox.brokers import kafka, rabbitmq, redis


@pytest.mark.parametrize(
    ("name", "backend_module"),
    [("KafkaBroker", kafka), ("RabbitMQBroker", rabbitmq), ("RedisBroker", redis)],
)
def test_lazy_constructor_builds_backend_broker(monkeypatch, name, backend_module):
    """Calling the package-level name constructs the real backend class with the same args."""
    backend_cls = MagicMock(name=name)
    monkeypatch.setattr(backend_module, name, backend_cls)
    config = object()

    broker = getattr(brokers, name)(config, extra="x")

    backend_cls.assert_called_once_with(config, extra="x")
    assert broker is backend_cls.return_value


@pytest.mark.parametrize(
    ("name", "backend_module"),
    [("KafkaBroker", kafka), ("RabbitMQBroker", rabbitmq), ("RedisBroker", redis)],
)
def test_lazy_constructor_returns_backend_instance(name, backend_module):
    """Without mocks, the wrapper yields an instance of the backend class (or its dep error)."""
    from sagaz.core.exceptions import MissingDependencyError

    try:
        broker = getattr(brokers, name)()
    except MissingDependencyError:
        pytest.skip(f"optional dependency for {name} not installed")
    assert isinstance(broker, getattr(backend_module, name))
