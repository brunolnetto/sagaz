from typing import Any
import asyncio
import uuid

from sagaz.triggers.registry import TriggerRegistry
from sagaz.triggers.decorators import TriggerMetadata
from sagaz.logger import get_logger
from sagaz.config import get_config
from sagaz.types import SagaStatus

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
        pass
        
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
        started_saga_ids = []
        
        if not triggers:
            logger.debug(f"No triggers registered for source '{source}'")
            return []
            
        logger.info(f"Processing event from '{source}' for {len(triggers)} triggers")
        
        for trigger in triggers:
            saga_class = trigger.saga_class
            method_name = trigger.method_name
            metadata: TriggerMetadata = trigger.metadata
            
            try:
                # 1. Transform payload to context
                context = await self._run_transformer(saga_class, method_name, payload)
                
                # If transformer returns None, ignore the event
                if context is None:
                    continue
                    
                if not isinstance(context, dict):
                    logger.warning(
                        f"Trigger {saga_class.__name__}.{method_name} returned non-dict context. Ignoring."
                    )
                    continue
                
                # 2. Derive Idempotency Key (if configured)
                saga_id = self._derive_saga_id(metadata, payload)
                
                # 3. Check Idempotency (if key derived)
                if saga_id:
                    existing = await self._check_idempotency(saga_id, saga_class.__name__)
                    if existing:
                        logger.info(f"Idempotent skip: Saga {saga_id} already exists.")
                        started_saga_ids.append(saga_id)
                        continue
                else:
                    # Generate new random ID if not idempotent
                    saga_id = str(uuid.uuid4())
                
                # 4. Check Concurrency (if configured)
                if metadata.max_concurrent:
                    # Use saga_name attribute if defined, else class name
                    name_for_query = getattr(saga_class, 'saga_name', None) or saga_class.__name__
                    allowed = await self._check_concurrency(
                        name_for_query, 
                        metadata.max_concurrent
                    )
                    if not allowed:
                        logger.warning(
                            f"Concurrency limit ({metadata.max_concurrent}) reached for {saga_class.__name__}. Skipping."
                        )
                        continue

                # 5. Create and Run Saga
                await self._run_saga(saga_class, saga_id, context)
                started_saga_ids.append(saga_id)
                
            except Exception as e:
                logger.exception(
                    f"Error processing trigger {saga_class.__name__}.{method_name}: {e}"
                )
                
        return started_saga_ids

    async def _run_transformer(self, saga_class, method_name, payload) -> dict | None:
        """Run the transformer method (sync or async)."""
        saga_instance = saga_class()
        transformer = getattr(saga_instance, method_name)
        
        if asyncio.iscoroutinefunction(transformer):
            return await transformer(payload)
        return transformer(payload)

    def _derive_saga_id(self, metadata: TriggerMetadata, payload: Any) -> str | None:
        """Derive deterministic Saga ID if idempotency key logic is provided."""
        key_logic = metadata.idempotency_key
        
        if not key_logic:
            return None
            
        key_str = None
        if isinstance(key_logic, str):
            # If string, assume it's a key in the payload (if payload is dict)
            if isinstance(payload, dict):
                value = payload.get(key_logic)
                if value is not None:
                    key_str = str(value)
            elif hasattr(payload, key_logic):
                value = getattr(payload, key_logic)
                if value is not None:
                    key_str = str(value)
        elif callable(key_logic):
            try:
                result = key_logic(payload)
                if result is not None:
                    key_str = str(result)
            except Exception as e:
                logger.error(f"Error calculating idempotency key: {e}")
                return None
        
        if not key_str:
            return None
            
        # Create deterministic UUID from key
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, key_str))

    async def _check_idempotency(self, saga_id: str, saga_name: str) -> bool:
        """Check if saga with this ID already exists."""
        if not self.storage:
            return False
            
        try:
            state = await self.storage.load_saga_state(saga_id)
            return state is not None
        except Exception as e:
            logger.warning(f"Storage error during idempotency check: {e}")
            return False

    async def _check_concurrency(self, saga_name: str, max_concurrent: int) -> bool:
        """Check if we can run more sagas of this type."""
        if not self.storage:
            return True  # Fail open if no storage
            
        try:
            executing = await self.storage.list_sagas(
                status=SagaStatus.EXECUTING,
                saga_name=saga_name,
                limit=max_concurrent + 1
            )
            return len(executing) < max_concurrent
        except Exception as e:
            logger.warning(f"Storage error during concurrency check: {e}")
            return True

    async def _run_saga(self, saga_class, saga_id: str, context: dict):
        """Instantiate and run the saga."""
        execution_saga = saga_class()
        
        logger.info(f"Trigger {saga_class.__name__} starting saga {saga_id}")
        
        # Schedule background execution - pass saga_id to run()
        loop = asyncio.get_running_loop()
        task = loop.create_task(execution_saga.run(context, saga_id=saga_id))
        
        def _log_error(t):
            try:
                t.result()
            except Exception as e:
                logger.error(f"Saga execution failed: {e}")
                
        task.add_done_callback(_log_error)


# Singleton instance
_engine = TriggerEngine()

async def fire_event(source: str, payload: Any) -> list[str]:
    """Public API to fire events."""
    return await _engine.fire(source, payload)
