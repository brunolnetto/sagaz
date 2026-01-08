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

from sagaz.triggers.decorators import TriggerMetadata, trigger
from sagaz.triggers.engine import TriggerEngine, fire_event
from sagaz.triggers.registry import RegisteredTrigger, TriggerRegistry
from sagaz.triggers.sources.broker import BrokerTriggerConsumer

# Phase 3: Sources
from sagaz.triggers.sources.cron import CronScheduler

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
