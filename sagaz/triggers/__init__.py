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

from sagaz.triggers.decorators import trigger, TriggerMetadata
from sagaz.triggers.registry import TriggerRegistry, RegisteredTrigger
from sagaz.triggers.engine import fire_event, TriggerEngine

# Phase 3: Sources
from sagaz.triggers.sources.cron import CronScheduler
from sagaz.triggers.sources.broker import BrokerTriggerConsumer

__all__ = [
    # Core
    "trigger",
    "TriggerMetadata",
    "TriggerRegistry",
    "RegisteredTrigger",
    "fire_event",
    "TriggerEngine",
    # Sources
    "CronScheduler",
    "BrokerTriggerConsumer",
]
