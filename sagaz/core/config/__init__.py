"""
SagaConfig - Unified configuration for the Saga framework.

Provides a single, type-safe configuration object that wires together:
- Storage backend (for saga state persistence)
- Message broker (for outbox pattern)
- Observability (metrics, tracing, logging)

IMPORTANT: You must choose ONE storage approach:
  - Option 1: Use `storage_manager` for unified saga + outbox storage
  - Option 2: Use `storage` and optionally `outbox_storage` separately
  Mixing both approaches will raise a ValueError.

Example (Option 1 - unified StorageManager, RECOMMENDED):
    >>> from sagaz import SagaConfig, configure
    >>> from sagaz.core.storage import create_storage_manager
    >>>
    >>> # StorageManager provides unified access to saga + outbox storage
    >>> # with shared connection pooling
    >>> manager = create_storage_manager("postgresql://localhost/db")
    >>> await manager.initialize()
    >>>
    >>> config = SagaConfig(
    ...     storage_manager=manager,  # Replaces storage + outbox_storage
    ...     broker=KafkaBroker(bootstrap_servers="localhost:9092"),
    ...     metrics=True,
    ... )
    >>>
    >>> configure(config)

Example (Option 2 - separate storage instances):
    >>> from sagaz import SagaConfig, configure
    >>> from sagaz.core.storage import PostgreSQLSagaStorage
    >>> from sagaz.core.outbox.brokers import KafkaBroker
    >>>
    >>> config = SagaConfig(
    ...     storage=PostgreSQLSagaStorage("postgresql://localhost/db"),
    ...     broker=KafkaBroker(bootstrap_servers="localhost:9092"),
    ...     metrics=True,
    ... )
    >>>
    >>> configure(config)
"""

from __future__ import annotations

from typing import Any

from sagaz.core.config import _config
from sagaz.core.config._broker import BrokerConfigManager
from sagaz.core.config._config import SagaConfig, configure, get_config, logger
from sagaz.core.config._storage import StorageConfigManager


def __getattr__(name: str) -> Any:
    """Expose the live global ``SagaConfig`` (owned by ``_config``) as ``_global_config``."""
    if name == "_global_config":
        return _config._global_config
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted([*globals(), "_global_config"])


__all__ = [
    "BrokerConfigManager",
    "SagaConfig",
    "StorageConfigManager",
    "configure",
    "get_config",
]
