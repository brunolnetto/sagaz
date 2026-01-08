"""
Cron scheduler for periodic saga triggering.

Provides a scheduler that fires events based on cron expressions,
allowing sagas to run on schedules (e.g., hourly, daily, weekly).

Example:
    class CleanupSaga(Saga):
        @trigger(source="cron", schedule="0 2 * * *")  # Daily at 2 AM
        def on_daily(self, event):
            return {"date": event["timestamp"].date()}

        @action("cleanup")
        async def cleanup(self, ctx):
            await cleanup_old_records()

    # Start scheduler
    scheduler = CronScheduler()
    await scheduler.start()
"""

import asyncio
from datetime import datetime
from typing import Any

from sagaz.logger import get_logger
from sagaz.triggers import fire_event
from sagaz.triggers.registry import TriggerRegistry

logger = get_logger(__name__)


def _parse_cron(expression: str) -> dict:
    """
    Parse a cron expression into components.

    Format: minute hour day month weekday
    Supports: * (any), */n (every n), n (specific value)
    """
    parts = expression.split()
    if len(parts) != 5:
        msg = f"Invalid cron expression: {expression}"
        raise ValueError(msg)

    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "weekday": parts[4],
    }


def _matches_field(field: str, value: int) -> bool:
    """Check if a cron field matches a value."""
    if field == "*":
        return True

    if field.startswith("*/"):
        step = int(field[2:])
        return value % step == 0

    if "," in field:
        return value in [int(v) for v in field.split(",")]

    if "-" in field:
        start, end = field.split("-")
        return int(start) <= value <= int(end)

    return value == int(field)


def _matches_cron(expression: str, dt: datetime) -> bool:
    """Check if a datetime matches a cron expression."""
    try:
        cron = _parse_cron(expression)
        return (
            _matches_field(cron["minute"], dt.minute) and
            _matches_field(cron["hour"], dt.hour) and
            _matches_field(cron["day"], dt.day) and
            _matches_field(cron["month"], dt.month) and
            _matches_field(cron["weekday"], dt.weekday())
        )
    except Exception as e:
        logger.error(f"Error parsing cron expression '{expression}': {e}")
        return False


class CronScheduler:
    """
    Scheduler that triggers sagas on cron schedules.

    Finds all registered cron triggers and fires events when their
    schedules match the current time.

    Example:
        scheduler = CronScheduler()
        await scheduler.start()

        # ... application runs ...

        await scheduler.stop()
    """

    def __init__(self, tick_interval: int = 60):
        """
        Initialize the scheduler.

        Args:
            tick_interval: Seconds between schedule checks (default: 60)
        """
        self._running = False
        self._task: asyncio.Task | None = None
        self._tick_interval = tick_interval

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Cron scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Cron scheduler stopped")

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.exception(f"Error in cron tick: {e}")

            await asyncio.sleep(self._tick_interval)

    async def _tick(self) -> list[str]:
        """
        Check schedules and fire matching events.

        Returns:
            List of triggered saga IDs
        """
        now = datetime.now()
        triggered_ids = []

        # Get all cron triggers
        cron_triggers = TriggerRegistry.get_triggers("cron")

        for trigger in cron_triggers:
            schedule = trigger.metadata.config.get("schedule")
            if not schedule:
                continue

            if _matches_cron(schedule, now):
                # Fire event for this trigger
                event_data = {
                    "timestamp": now,
                    "schedule": schedule,
                    "trigger_name": trigger.method_name,
                }

                logger.debug(f"Cron trigger matched: {trigger.saga_class.__name__}.{trigger.method_name}")

                # Fire event (will trigger the saga)
                ids = await fire_event("cron", event_data)
                triggered_ids.extend(ids)

        return triggered_ids
