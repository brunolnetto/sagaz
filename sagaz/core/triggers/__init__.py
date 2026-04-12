"""
sagaz.triggers - Event-Driven Trigger System

Provides the ability to automatically trigger Sagas in response to events.

Example:
    class OrderSaga(Saga):
        @trigger(source="webhook", idempotency_key="order_id")
        def on_order(self, event):
            return {"order_id": event["id"]}

        @action("process")
        async def process(self, ctx):
            ...

    # Fire event programmatically
    await fire_event("webhook", {"id": "123"})
"""

from sagaz.core.triggers.decorators import TriggerMetadata, trigger
from sagaz.core.triggers.engine import TriggerEngine, fire_event
from sagaz.core.triggers.registry import RegisteredTrigger, TriggerRegistry
from sagaz.core.triggers.sources.broker import BrokerTriggerConsumer

# Phase 3: Sources
from sagaz.core.triggers.sources.cron import CronScheduler

__all__ = [
    "BrokerTriggerConsumer",
    # Sources
    "CronScheduler",
    "RegisteredTrigger",
    "TriggerEngine",
    "TriggerMetadata",
    "TriggerRegistry",
    "fire_event",
    # Core
    "trigger",
]
