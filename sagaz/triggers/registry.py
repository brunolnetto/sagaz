import logging
from dataclasses import dataclass
from typing import Any

from sagaz.triggers.decorators import TriggerMetadata

logger = logging.getLogger(__name__)


@dataclass
class RegisteredTrigger:
    """A fully registered trigger."""

    saga_class: type[Any]  # The Saga class
    method_name: str  # The method name (e.g. "on_order")
    metadata: TriggerMetadata


class TriggerRegistry:
    """
    Global registry for Saga triggers.

    Maps event sources to a list of registered triggers.
    """

    # Map[source_type, list[RegisteredTrigger]]
    _registry: dict[str, list[RegisteredTrigger]] = {}

    @classmethod
    def register(cls, saga_class: type[Any], method_name: str, metadata: TriggerMetadata) -> None:
        """Register a trigger for a saga class."""
        source = metadata.source
        if source not in cls._registry:
            cls._registry[source] = []

        trigger = RegisteredTrigger(saga_class, method_name, metadata)
        cls._registry[source].append(trigger)

        # Warn if idempotency_key is not configured
        if not metadata.idempotency_key:
            logger.warning(
                f"\n{'=' * 70}\n"
                f"⚠️  IDEMPOTENCY WARNING\n"
                f"{'=' * 70}\n"
                f"Trigger: {saga_class.__name__}.{method_name}\n"
                f"Source: {source}\n"
                f"\n"
                f"No idempotency key configured. This trigger may execute\n"
                f"duplicate sagas if the same event is received multiple times.\n"
                f"\n"
                f"To enable idempotency protection, add an idempotency_key:\n"
                f"\n"
                f"  @trigger(\n"
                f"      source='{source}',\n"
                f"      idempotency_key='event_id'  # Field name in payload\n"
                f"  )\n"
                f"  # OR with custom logic:\n"
                f"  @trigger(\n"
                f"      source='{source}',\n"
                f"      idempotency_key=lambda p: f\"{{p['order_id']}}-{{p['version']}}\"\n"
                f"  )\n"
                f"{'=' * 70}\n"
            )

    @classmethod
    def get_triggers(cls, source: str) -> list[RegisteredTrigger]:
        """Get all triggers registered for a specific source."""
        return cls._registry.get(source, [])

    @classmethod
    def get_all(cls) -> dict[str, list[RegisteredTrigger]]:
        """Get the entire registry."""
        return cls._registry.copy()

    @classmethod
    def clear(cls) -> None:
        """Clear the registry (useful for tests)."""
        cls._registry.clear()
