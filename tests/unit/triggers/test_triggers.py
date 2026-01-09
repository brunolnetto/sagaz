"""
Comprehensive tests for the Event Triggers feature (ADR-025).

Tests cover:
- @trigger decorator and TriggerMetadata
- TriggerRegistry (registration, lookup, clear)
- TriggerEngine (fire_event, transformers, concurrency, idempotency)
- Declarative Saga persistence integration
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz import Saga, SagaConfig, action
from sagaz.core.config import configure, get_config
from sagaz.triggers import fire_event, trigger
from sagaz.triggers.decorators import TriggerMetadata
from sagaz.triggers.engine import TriggerEngine
from sagaz.triggers.registry import RegisteredTrigger, TriggerRegistry
from sagaz.core.types import SagaStatus

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_registry():
    """Clear the trigger registry before each test."""
    TriggerRegistry.clear()
    yield
    TriggerRegistry.clear()


@pytest.fixture
def memory_storage():
    """Provide fresh memory storage for each test."""
    from sagaz.storage import InMemorySagaStorage
    storage = InMemorySagaStorage()
    config = SagaConfig(storage=storage)
    configure(config)
    return storage


# =============================================================================
# @trigger Decorator Tests
# =============================================================================

class TestTriggerDecorator:
    """Tests for the @trigger decorator."""

    def test_basic_trigger_attaches_metadata(self):
        """@trigger attaches _trigger_metadata to method."""
        @trigger(source="webhook")
        def on_event(self, payload):
            return payload

        assert hasattr(on_event, "_trigger_metadata")
        assert isinstance(on_event._trigger_metadata, TriggerMetadata)
        assert on_event._trigger_metadata.source == "webhook"

    def test_trigger_with_max_concurrent(self):
        """@trigger stores max_concurrent in metadata."""
        @trigger(source="kafka", max_concurrent=5)
        def handler(self, payload):
            return payload

        assert handler._trigger_metadata.max_concurrent == 5

    def test_trigger_with_idempotency_key_string(self):
        """@trigger stores string idempotency_key."""
        @trigger(source="api", idempotency_key="request_id")
        def handler(self, payload):
            return payload

        assert handler._trigger_metadata.idempotency_key == "request_id"

    def test_trigger_with_idempotency_key_callable(self):
        """@trigger stores callable idempotency_key."""
        def key_fn(p):
            return f"{p['type']}:{p['id']}"

        @trigger(source="api", idempotency_key=key_fn)
        def handler(self, payload):
            return payload

        assert handler._trigger_metadata.idempotency_key is key_fn

    def test_trigger_with_extra_config(self):
        """@trigger stores extra config in config dict."""
        @trigger(source="kafka", topic="orders", event_type="order.created")
        def handler(self, payload):
            return payload

        assert handler._trigger_metadata.config["topic"] == "orders"
        assert handler._trigger_metadata.config["event_type"] == "order.created"


# =============================================================================
# TriggerRegistry Tests
# =============================================================================

class TestTriggerRegistry:
    """Tests for TriggerRegistry."""

    def test_register_and_get_triggers(self):
        """Register a trigger and retrieve it."""
        metadata = TriggerMetadata(source="test_source", config={})
        TriggerRegistry.register(object, "on_event", metadata)

        triggers = TriggerRegistry.get_triggers("test_source")
        assert len(triggers) == 1
        assert triggers[0].method_name == "on_event"
        assert triggers[0].metadata.source == "test_source"

    def test_get_triggers_empty_source(self):
        """get_triggers returns empty list for unknown source."""
        triggers = TriggerRegistry.get_triggers("nonexistent")
        assert triggers == []

    def test_multiple_triggers_same_source(self):
        """Multiple sagas can register for same source."""
        metadata = TriggerMetadata(source="shared_source", config={})
        TriggerRegistry.register(object, "handler1", metadata)
        TriggerRegistry.register(str, "handler2", metadata)

        triggers = TriggerRegistry.get_triggers("shared_source")
        assert len(triggers) == 2

    def test_get_all_registry(self):
        """get_all returns copy of entire registry."""
        TriggerRegistry.register(object, "h1", TriggerMetadata(source="a", config={}))
        TriggerRegistry.register(object, "h2", TriggerMetadata(source="b", config={}))

        all_triggers = TriggerRegistry.get_all()
        assert "a" in all_triggers
        assert "b" in all_triggers

    def test_clear_registry(self):
        """clear() removes all registered triggers."""
        TriggerRegistry.register(object, "h", TriggerMetadata(source="s", config={}))
        TriggerRegistry.clear()

        assert TriggerRegistry.get_triggers("s") == []
        assert TriggerRegistry.get_all() == {}


# =============================================================================
# Saga Auto-Registration Tests
# =============================================================================

class TestSagaAutoRegistration:
    """Tests for automatic trigger registration via __init_subclass__."""

    def test_saga_with_trigger_auto_registers(self):
        """Saga subclass with @trigger auto-registers with registry."""
        class AutoRegSaga(Saga):
            @trigger(source="auto_test")
            def on_event(self, payload):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        triggers = TriggerRegistry.get_triggers("auto_test")
        assert len(triggers) == 1
        assert triggers[0].saga_class is AutoRegSaga
        assert triggers[0].method_name == "on_event"

    def test_saga_with_multiple_triggers(self):
        """Saga can have multiple triggers."""
        class MultiTriggerSaga(Saga):
            @trigger(source="source_a")
            def on_a(self, payload):
                return {"from": "a"}

            @trigger(source="source_b")
            def on_b(self, payload):
                return {"from": "b"}

            @action("process")
            async def process(self, ctx):
                return {}

        assert len(TriggerRegistry.get_triggers("source_a")) == 1
        assert len(TriggerRegistry.get_triggers("source_b")) == 1

    def test_saga_without_trigger_does_not_register(self):
        """Saga without @trigger does not add to registry."""
        initial_count = len(TriggerRegistry.get_all())

        class PlainSaga(Saga):
            @action("step")
            async def step(self, ctx):
                return {}

        # Registry should not have grown
        assert len(TriggerRegistry.get_all()) == initial_count


# =============================================================================
# TriggerEngine Tests
# =============================================================================

class TestTriggerEngine:
    """Tests for TriggerEngine.fire()."""

    @pytest.mark.asyncio
    async def test_fire_with_no_triggers_returns_empty(self, memory_storage):
        """fire_event returns empty list when no triggers registered."""
        result = await fire_event("unknown_source", {"data": 123})
        assert result == []

    @pytest.mark.asyncio
    async def test_fire_calls_transformer(self, memory_storage):
        """fire_event calls the transformer method."""
        called = []

        class TransformerSaga(Saga):
            saga_name = "transformer_test"

            @trigger(source="transformer_source")
            def on_event(self, payload):
                called.append(payload)
                return {"transformed": True}

            @action("step")
            async def step(self, ctx):
                return {}

        await fire_event("transformer_source", {"original": True})
        await asyncio.sleep(0.1)  # Let background task start

        assert len(called) == 1
        assert called[0] == {"original": True}

    @pytest.mark.asyncio
    async def test_fire_skips_if_transformer_returns_none(self, memory_storage):
        """fire_event skips saga if transformer returns None."""
        class SkipSaga(Saga):
            saga_name = "skip_test"

            @trigger(source="skip_source")
            def on_event(self, payload):
                return None  # Skip this event

            @action("step")
            async def step(self, ctx):
                return {}

        result = await fire_event("skip_source", {})
        assert result == []

    @pytest.mark.asyncio
    async def test_fire_skips_if_transformer_returns_non_dict(self, memory_storage):
        """fire_event skips saga if transformer returns non-dict."""
        class BadTransformerSaga(Saga):
            saga_name = "bad_transformer"

            @trigger(source="bad_source")
            def on_event(self, payload):
                return "not a dict"

            @action("step")
            async def step(self, ctx):
                return {}

        result = await fire_event("bad_source", {})
        assert result == []

    @pytest.mark.asyncio
    async def test_fire_with_async_transformer(self, memory_storage):
        """fire_event supports async transformer methods."""
        class AsyncTransformerSaga(Saga):
            saga_name = "async_transformer"

            @trigger(source="async_source")
            async def on_event(self, payload):
                await asyncio.sleep(0.01)
                return {"async": True}

            @action("step")
            async def step(self, ctx):
                return {}

        result = await fire_event("async_source", {})
        assert len(result) == 1


# =============================================================================
# Concurrency Control Tests
# =============================================================================

class TestConcurrencyControl:
    """Tests for max_concurrent enforcement."""

    @pytest.mark.asyncio
    async def test_concurrency_allows_within_limit(self, memory_storage):
        """Sagas within max_concurrent limit are allowed."""
        class TwoAtOnceSaga(Saga):
            saga_name = "two_at_once"

            @trigger(source="two_source", max_concurrent=2)
            def on_event(self, payload):
                return {"id": payload["id"]}

            @action("slow")
            async def slow_step(self, ctx):
                await asyncio.sleep(0.3)
                return {}

        # Fire two events quickly
        ids1 = await fire_event("two_source", {"id": 1})
        await asyncio.sleep(0.05)  # Let first start
        ids2 = await fire_event("two_source", {"id": 2})

        # Both should be allowed
        assert len(ids1) == 1
        assert len(ids2) == 1

    @pytest.mark.asyncio
    async def test_concurrency_blocks_over_limit(self, memory_storage):
        """Sagas over max_concurrent limit are blocked."""
        class OneAtTimeSaga(Saga):
            saga_name = "one_at_time"

            @trigger(source="one_source", max_concurrent=1)
            def on_event(self, payload):
                return {"id": payload["id"]}

            @action("slow")
            async def slow_step(self, ctx):
                await asyncio.sleep(0.5)
                return {}

        # Fire first event
        ids1 = await fire_event("one_source", {"id": 1})
        assert len(ids1) == 1

        # Wait for it to be executing
        for _ in range(20):
            state = await memory_storage.load_saga_state(ids1[0])
            if state and state["status"] == SagaStatus.EXECUTING.value:
                break
            await asyncio.sleep(0.05)

        # Fire second event - should be blocked
        ids2 = await fire_event("one_source", {"id": 2})
        assert len(ids2) == 0

    @pytest.mark.asyncio
    async def test_concurrency_allows_after_completion(self, memory_storage):
        """Saga allowed after previous completes."""
        class QuickSaga(Saga):
            saga_name = "quick_saga"

            @trigger(source="quick_source", max_concurrent=1)
            def on_event(self, payload):
                return {"id": payload["id"]}

            @action("fast")
            async def fast_step(self, ctx):
                return {}  # Completes immediately

        # Fire first event
        ids1 = await fire_event("quick_source", {"id": 1})
        assert len(ids1) == 1

        # Wait for completion
        await asyncio.sleep(0.2)

        # Fire second - should be allowed now
        ids2 = await fire_event("quick_source", {"id": 2})
        assert len(ids2) == 1


# =============================================================================
# Idempotency Tests
# =============================================================================

class TestIdempotency:
    """Tests for idempotency_key enforcement."""

    @pytest.mark.asyncio
    async def test_idempotency_same_key_returns_same_id(self, memory_storage):
        """Same idempotency key returns same saga ID."""
        class IdempotentSaga(Saga):
            saga_name = "idempotent"

            @trigger(source="idem_source", idempotency_key="key")
            def on_event(self, payload):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        # First call
        ids1 = await fire_event("idem_source", {"key": "same-key"})
        assert len(ids1) == 1

        # Wait for persistence
        await asyncio.sleep(0.15)

        # Second call with same key
        ids2 = await fire_event("idem_source", {"key": "same-key"})
        assert len(ids2) == 1
        assert ids1[0] == ids2[0]

    @pytest.mark.asyncio
    async def test_idempotency_different_keys_create_different_sagas(self, memory_storage):
        """Different idempotency keys create different sagas."""
        class DiffKeySaga(Saga):
            saga_name = "diff_key"

            @trigger(source="diff_source", idempotency_key="key")
            def on_event(self, payload):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        ids1 = await fire_event("diff_source", {"key": "key-1"})
        ids2 = await fire_event("diff_source", {"key": "key-2"})

        assert len(ids1) == 1
        assert len(ids2) == 1
        assert ids1[0] != ids2[0]

    @pytest.mark.asyncio
    async def test_idempotency_with_callable_key(self, memory_storage):
        """idempotency_key can be a callable."""
        class CallableKeySaga(Saga):
            saga_name = "callable_key"

            @trigger(
                source="callable_source",
                idempotency_key=lambda p: f"{p['type']}:{p['id']}"
            )
            def on_event(self, payload):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        # Same composite key
        ids1 = await fire_event("callable_source", {"type": "order", "id": "123"})
        await asyncio.sleep(0.15)
        ids2 = await fire_event("callable_source", {"type": "order", "id": "123"})

        assert ids1[0] == ids2[0]

    @pytest.mark.asyncio
    async def test_idempotency_missing_key_field_generates_random_id(self, memory_storage):
        """Missing idempotency key field results in random ID generation."""
        class MissingKeySaga(Saga):
            saga_name = "missing_key"

            @trigger(source="missing_source", idempotency_key="nonexistent_field")
            def on_event(self, payload):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        ids1 = await fire_event("missing_source", {"other": "data"})
        ids2 = await fire_event("missing_source", {"other": "data"})

        # Should generate random IDs (different each time)
        assert len(ids1) == 1
        assert len(ids2) == 1
        assert ids1[0] != ids2[0]


# =============================================================================
# Persistence Tests
# =============================================================================

class TestSagaPersistence:
    """Tests for saga state persistence."""

    @pytest.mark.asyncio
    async def test_saga_persists_executing_state(self, memory_storage):
        """Saga persists EXECUTING state on start."""
        class PersistSaga(Saga):
            saga_name = "persist_test"

            @trigger(source="persist_source")
            def on_event(self, payload):
                return {}

            @action("slow")
            async def slow_step(self, ctx):
                await asyncio.sleep(0.5)
                return {}

        ids = await fire_event("persist_source", {})
        saga_id = ids[0]

        # Wait for execution to start
        for _ in range(10):
            state = await memory_storage.load_saga_state(saga_id)
            if state:
                break
            await asyncio.sleep(0.05)

        assert state is not None
        assert state["status"] == SagaStatus.EXECUTING.value

    @pytest.mark.asyncio
    async def test_saga_persists_completed_state(self, memory_storage):
        """Saga persists COMPLETED state on success."""
        class CompleteSaga(Saga):
            saga_name = "complete_test"

            @trigger(source="complete_source")
            def on_event(self, payload):
                return {}

            @action("fast")
            async def fast_step(self, ctx):
                return {}

        ids = await fire_event("complete_source", {})
        saga_id = ids[0]

        # Wait for completion
        await asyncio.sleep(0.2)

        state = await memory_storage.load_saga_state(saga_id)
        assert state is not None
        assert state["status"] == SagaStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_saga_persists_rolled_back_state_on_failure(self, memory_storage):
        """Saga persists ROLLED_BACK state on failure."""
        class FailSaga(Saga):
            saga_name = "fail_test"

            @trigger(source="fail_source")
            def on_event(self, payload):
                return {}

            @action("fail")
            async def fail_step(self, ctx):
                msg = "Intentional failure"
                raise ValueError(msg)

        ids = await fire_event("fail_source", {})
        saga_id = ids[0]

        # Wait for failure handling
        await asyncio.sleep(0.2)

        state = await memory_storage.load_saga_state(saga_id)
        assert state is not None
        assert state["status"] == SagaStatus.ROLLED_BACK.value


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_empty_payload(self, memory_storage):
        """fire_event handles empty payload."""
        class EmptyPayloadSaga(Saga):
            saga_name = "empty_payload"

            @trigger(source="empty_source")
            def on_event(self, payload):
                return {"received": payload}

            @action("step")
            async def step(self, ctx):
                return {}

        result = await fire_event("empty_source", {})
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_saga_without_saga_name_attribute(self, memory_storage):
        """Saga without saga_name uses class name."""
        class NoNameSaga(Saga):
            # No saga_name defined

            @trigger(source="noname_source")
            def on_event(self, payload):
                return {}

            @action("step")
            async def step(self, ctx):
                return {}

        result = await fire_event("noname_source", {})
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_transformer_exception_handled(self, memory_storage):
        """Exception in transformer is handled gracefully."""
        class ExceptionSaga(Saga):
            saga_name = "exception_saga"

            @trigger(source="exception_source")
            def on_event(self, payload):
                msg = "Transformer failed!"
                raise RuntimeError(msg)

            @action("step")
            async def step(self, ctx):
                return {}

        # Should not raise, just return empty
        result = await fire_event("exception_source", {})
        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_sagas_for_same_source(self, memory_storage):
        """Multiple sagas can be triggered by same source."""
        class SagaA(Saga):
            saga_name = "saga_a"

            @trigger(source="multi_source")
            def on_event(self, payload):
                return {"saga": "a"}

            @action("step")
            async def step(self, ctx):
                return {}

        class SagaB(Saga):
            saga_name = "saga_b"

            @trigger(source="multi_source")
            def on_event(self, payload):
                return {"saga": "b"}

            @action("step")
            async def step(self, ctx):
                return {}

        result = await fire_event("multi_source", {})
        assert len(result) == 2  # Both sagas triggered
