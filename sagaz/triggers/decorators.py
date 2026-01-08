from dataclasses import dataclass
from typing import Any, Callable, TypeVar

# Type for decorated function
F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class TriggerMetadata:
    """Metadata for a saga trigger definition."""
    source: str
    config: dict[str, Any]
    
    # Optional concurrency controls
    max_concurrent: int | None = None
    rate_limit: float | None = None  # per second
    
    # Idempotency
    idempotency_key: str | Callable[[Any], str] | None = None


def trigger(
    source: str,
    *,
    max_concurrent: int | None = None,
    rate_limit: float | None = None,
    idempotency_key: str | Callable[[Any], str] | None = None,
    **kwargs
):
    """
    Decorator to mark a Saga method as an event trigger (transformer).
    
    The decorated method receives an event and must return a context dict
    to start the saga, or None to ignore the event.
    
    Args:
        source: The source identifier (e.g., "kafka", "cron", "webhook", "manual")
        max_concurrent: Max concurrent sagas started by this trigger
        rate_limit: Max triggers per second
        idempotency_key: Key or function to derive unique ID for event deduplication
        **kwargs: Source-specific configuration (e.g., topic="orders", schedule="@daily")
        
    Example:
        @trigger(source="kafka", topic="orders.created")
        def on_order(self, event):
            return {"order_id": event.id}
    """
    def decorator(func: F) -> F:
        func._trigger_metadata = TriggerMetadata(
            source=source,
            config=kwargs,
            max_concurrent=max_concurrent,
            rate_limit=rate_limit,
            idempotency_key=idempotency_key,
        )
        return func
    return decorator
