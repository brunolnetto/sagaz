from dataclasses import dataclass
from typing import Any, Type

from sagaz.triggers.decorators import TriggerMetadata


@dataclass
class RegisteredTrigger:
    """A fully registered trigger."""
    saga_class: Type[Any]  # The Saga class
    method_name: str       # The method name (e.g. "on_order")
    metadata: TriggerMetadata


class TriggerRegistry:
    """
    Global registry for Saga triggers.
    
    Maps event sources to a list of registered triggers.
    """
    
    # Map[source_type, list[RegisteredTrigger]]
    _registry: dict[str, list[RegisteredTrigger]] = {}
    
    @classmethod
    def register(cls, saga_class: Type[Any], method_name: str, metadata: TriggerMetadata) -> None:
        """Register a trigger for a saga class."""
        source = metadata.source
        if source not in cls._registry:
            cls._registry[source] = []
            
        trigger = RegisteredTrigger(saga_class, method_name, metadata)
        cls._registry[source].append(trigger)
        
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
