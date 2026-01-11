import asyncio
import uuid
from typing import Any

from sagaz.core.config import get_config
from sagaz.core.logger import get_logger
from sagaz.core.types import SagaStatus
from sagaz.triggers.decorators import TriggerMetadata
from sagaz.triggers.registry import TriggerRegistry

logger = get_logger(__name__)


class TriggerEngine:
    """
    Engine for processing events and triggering sagas.

    Handles:
    - Trigger lookup
    - Payload transformation
    - Concurrency control
    - Idempotency checks
    - Saga execution
    """

    def __init__(self):
        self._background_tasks = set()

    @property
    def storage(self):
        return get_config().storage

    async def fire(self, source: str, payload: Any) -> list[str]:
        """
        Fire an event to trigger registered sagas.

        Args:
            source: Source identifier (e.g. "webhook", "kafka")
            payload: The event data

        Returns:
            List of started (or existing) saga IDs.
        """
        triggers = TriggerRegistry.get_triggers(source)

        if not triggers:
            logger.debug(f"No triggers registered for source '{source}'")
            return []

        logger.info(f"Processing event from '{source}' for {len(triggers)} triggers")

        results = await asyncio.gather(
            *[self._process_trigger(t, payload) for t in triggers], return_exceptions=True
        )

        # Filter out None and exceptions
        return [r for r in results if isinstance(r, str)]

    async def _process_trigger(self, trigger, payload: Any) -> str | None:
        """Process a single trigger. Returns saga_id if started or exists, None otherwise."""
        saga_class = trigger.saga_class
        method_name = trigger.method_name
        metadata: TriggerMetadata = trigger.metadata

        try:
            # 1. Transform payload to context
            context = await self._run_transformer(saga_class, method_name, payload)
            if not self._is_valid_context(context, saga_class, method_name):
                return None

            # 2. Get or generate saga ID
            saga_id, is_new = await self._resolve_saga_id(metadata, payload, saga_class)
            if saga_id is None:  # pragma: no cover
                return None  # pragma: no cover

            # If saga already exists (idempotent), return the ID without running
            if not is_new:
                return saga_id

            # 3. Check concurrency
            if not await self._is_concurrency_allowed(metadata, saga_class):
                return None

            # 4. Run saga
            if context is None:
                context = {}
            await self._run_saga(saga_class, saga_id, context)
            return saga_id

        except Exception as e:
            logger.exception(f"Error processing trigger {saga_class.__name__}.{method_name}: {e}")
            return None

    def _is_valid_context(self, context, saga_class, method_name) -> bool:
        """Check if transformer returned valid context."""
        if context is None:
            return False
        if not isinstance(context, dict):
            logger.warning(
                f"Trigger {saga_class.__name__}.{method_name} returned non-dict context. Ignoring."
            )
            return False
        return True

    async def _resolve_saga_id(
        self, metadata: TriggerMetadata, payload: Any, saga_class
    ) -> tuple[str | None, bool]:
        """
        Resolve saga ID with idempotency check.

        Returns:
            Tuple of (saga_id, is_new) where:
            - saga_id is the ID (derived or generated)
            - is_new is True if saga should be created, False if already exists
            Returns (None, False) on error
        """
        saga_id = self._derive_saga_id(metadata, payload)

        if saga_id:
            # Check if already exists
            if await self._check_idempotency(saga_id, saga_class.__name__):
                logger.info(f"Idempotent skip: Saga {saga_id} already exists.")
                return (saga_id, False)  # Return ID but mark as existing
        else:
            saga_id = str(uuid.uuid4())

        return (saga_id, True)

    async def _is_concurrency_allowed(self, metadata: TriggerMetadata, saga_class) -> bool:
        """Check if concurrency limit allows execution."""
        if not metadata.max_concurrent:
            return True

        name = getattr(saga_class, "saga_name", None) or saga_class.__name__
        allowed = await self._check_concurrency(name, metadata.max_concurrent)

        if not allowed:
            logger.warning(
                f"Concurrency limit ({metadata.max_concurrent}) reached for {saga_class.__name__}. Skipping."
            )
        return allowed

    async def _run_transformer(self, saga_class, method_name, payload) -> dict | None:
        """Run the transformer method (sync or async)."""
        saga_instance = saga_class()
        transformer = getattr(saga_instance, method_name)

        if asyncio.iscoroutinefunction(transformer):
            result = await transformer(payload)
            return dict(result) if result is not None else None
        result = transformer(payload)
        return dict(result) if result is not None else None

    def _derive_saga_id(self, metadata: TriggerMetadata, payload: Any) -> str | None:
        """Derive deterministic Saga ID if idempotency key logic is provided."""
        key_logic = metadata.idempotency_key

        if not key_logic:
            return None

        key_str = self._extract_key_value(key_logic, payload)

        if not key_str:
            return None

        return str(uuid.uuid5(uuid.NAMESPACE_DNS, key_str))

    def _extract_key_value(self, key_logic, payload: Any) -> str | None:
        """Extract the idempotency key value from payload."""
        if isinstance(key_logic, str):
            return self._extract_string_key(key_logic, payload)
        if callable(key_logic):
            return self._extract_callable_key(key_logic, payload)
        return None  # pragma: no cover

    def _extract_string_key(self, key: str, payload: Any) -> str | None:
        """Extract key from payload using string key."""
        if isinstance(payload, dict):
            value = payload.get(key)
        elif hasattr(payload, key):  # pragma: no cover
            value = getattr(payload, key)  # pragma: no cover
        else:  # pragma: no cover
            return None  # pragma: no cover

        return str(value) if value is not None else None

    def _extract_callable_key(self, func, payload: Any) -> str | None:
        """Extract key using callable."""
        try:
            result = func(payload)
            return str(result) if result is not None else None
        except Exception as e:  # pragma: no cover
            logger.error(f"Error calculating idempotency key: {e}")  # pragma: no cover
            return None  # pragma: no cover

    async def _check_idempotency(self, saga_id: str, saga_name: str) -> bool:
        """Check if saga with this ID already exists."""
        if not self.storage:
            return False  # pragma: no cover

        try:
            state = await self.storage.load_saga_state(saga_id)
            return state is not None
        except Exception as e:  # pragma: no cover
            logger.warning(f"Storage error during idempotency check: {e}")  # pragma: no cover
            return False  # pragma: no cover

    async def _check_concurrency(self, saga_name: str, max_concurrent: int) -> bool:
        """Check if concurrency limit allows new saga."""
        if not self.storage:
            return True  # pragma: no cover

        try:
            running = await self.storage.list_sagas(
                saga_name=saga_name, status=SagaStatus.EXECUTING
            )
            current_count = len(running) if running else 0
            return current_count < max_concurrent
        except Exception as e:  # pragma: no cover
            logger.warning(f"Storage error during concurrency check: {e}")  # pragma: no cover
            return True  # pragma: no cover

    async def _run_saga(self, saga_class, saga_id: str, context: dict):
        """Create and run saga instance in background.

        Uses create_task to run the saga asynchronously so that:
        1. fire_event returns immediately with the saga_id
        2. Concurrency control can work (check running sagas)
        3. Multiple events can be processed in parallel
        """
        saga_instance = saga_class()
        # Run in background - don't await completion
        task = asyncio.create_task(saga_instance.run(context, saga_id=saga_id))
        self._background_tasks.add(task)

        def _handle_task_done(t):
            """Handle task completion and cleanup."""
            self._background_tasks.discard(t)
            # Retrieve exception to prevent "Task exception was never retrieved" warning
            # The saga already logged and handled compensation, so we just silently consume it
            try:
                t.result()
            except Exception:
                pass  # Expected for failed sagas - already logged and compensated

        task.add_done_callback(_handle_task_done)


# Singleton instance
_engine = TriggerEngine()


async def fire_event(source: str, payload: Any) -> list[str]:
    """Fire an event to trigger registered sagas."""
    return await _engine.fire(source, payload)
