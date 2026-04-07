"""
Tests for missing paths in sagaz/triggers/engine.py.

Missing lines: 85, 97, 117, 120, 202, 211-212, 214, 223-225, 230,
              235-237, 242, 250-252
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz import Saga, SagaConfig, action
from sagaz.core.config import configure
from sagaz.triggers import trigger
from sagaz.triggers.decorators import TriggerMetadata
from sagaz.triggers.engine import TriggerEngine
from sagaz.triggers.registry import TriggerRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    TriggerRegistry.clear()
    yield
    TriggerRegistry.clear()


@pytest.fixture
def memory_storage():
    from sagaz.storage import InMemorySagaStorage

    storage = InMemorySagaStorage()
    config = SagaConfig(storage=storage)
    configure(config)
    return storage


# =============================================================================
# Line 85: fire() returns [] when no triggers registered
# =============================================================================


class TestFireNoTriggers:
    """Line 85: fire() with no triggers returns empty list."""

    @pytest.mark.asyncio
    async def test_fire_with_no_triggers_returns_empty(self):
        """Line 85: No triggers for source → returns []."""
        engine = TriggerEngine()

        result = await engine.fire("unregistered-source", {"key": "value"})

        assert result == []


# =============================================================================
# Line 97: _process_trigger returns None when saga_id is None
# =============================================================================


class TestProcessTriggerSagaIdNone:
    """Line 97: saga_id is None → returns None."""

    @pytest.mark.asyncio
    async def test_returns_none_when_saga_id_none(self):
        """Line 97: _resolve_saga_id returns None→ _process_trigger returns None."""
        engine = TriggerEngine()

        # Create a mock trigger with metadata
        class FakeSaga:
            __name__ = "FakeSaga"

        mock_trigger = MagicMock()
        mock_trigger.saga_class = FakeSaga
        mock_trigger.method_name = "on_event"
        mock_trigger.metadata = TriggerMetadata(source="test", config={})

        # Patch _run_transformer to return valid context
        # Patch _resolve_saga_id to return None, False
        with (
            patch.object(
                engine, "_run_transformer", new_callable=AsyncMock, return_value={"key": "val"}
            ),
            patch.object(
                engine, "_resolve_saga_id", new_callable=AsyncMock, return_value=(None, False)
            ),
        ):
            result = await engine._process_trigger(mock_trigger, {"event": "data"})

        assert result is None


# =============================================================================
# Lines 117, 120: _is_valid_context with non-dict context
# =============================================================================


class TestIsValidContext:
    """Lines 117, 120: non-dict context returns False."""

    def test_is_valid_context_none_returns_false(self):
        """_is_valid_context with None → False."""
        engine = TriggerEngine()

        class FakeSaga:
            pass

        result = engine._is_valid_context(None, FakeSaga, "on_event")
        assert result is False

    def test_is_valid_context_non_dict_returns_false(self):
        """Lines 117, 120: non-dict context logs warning and returns False."""

        class FakeSaga:
            pass

        engine = TriggerEngine()
        # Pass a list instead of dict
        result = engine._is_valid_context(["item1", "item2"], FakeSaga, "on_event")
        assert result is False

    def test_is_valid_context_dict_returns_true(self):
        """_is_valid_context with dict → True."""

        class FakeSaga:
            pass

        engine = TriggerEngine()
        result = engine._is_valid_context({"key": "value"}, FakeSaga, "on_event")
        assert result is True


# =============================================================================
# Line 202: _resolve_saga_id returns (saga_id, False) when idempotent (already exists)
# =============================================================================


class TestResolveSagaIdIdempotent:
    """Line 202: _resolve_saga_id returns (saga_id, False) when saga already exists."""

    @pytest.mark.asyncio
    async def test_resolve_saga_id_existing_returns_false_is_new(self, memory_storage):
        """Line 202: If saga already exists → (saga_id, False)."""
        engine = TriggerEngine()

        # Create a metadata with idempotency_key
        metadata = TriggerMetadata(source="test", config={}, idempotency_key="order_id")

        class FakeSaga:
            pass

        payload = {"order_id": "order-123"}

        # Pre-save a saga state so idempotency check finds it
        derived_id = engine._derive_saga_id(metadata, payload, FakeSaga)
        from sagaz.core.types import SagaStatus

        await memory_storage.save_saga_state(derived_id, "FakeSaga", SagaStatus.COMPLETED, [], {})

        saga_id, is_new = await engine._resolve_saga_id(metadata, payload, FakeSaga)

        assert saga_id == derived_id
        assert is_new is False  # Existing saga → not new


# =============================================================================
# Lines 211-212, 214: _resolve_saga_id when no idempotency → generates UUID
# =============================================================================


class TestResolveSagaIdNew:
    """Lines 211-212, 214: saga_id = uuid4() when no idempotency key."""

    @pytest.mark.asyncio
    async def test_resolve_saga_id_no_idempotency_generates_uuid(self):
        """Lines 211-212, 214: No idempotency key → new UUID, is_new=True."""
        engine = TriggerEngine()

        metadata = TriggerMetadata(source="test", config={}, idempotency_key=None)

        class FakeSaga:
            pass

        saga_id, is_new = await engine._resolve_saga_id(metadata, {"data": "val"}, FakeSaga)

        assert saga_id is not None
        assert is_new is True  # New saga


# =============================================================================
# Lines 223-225, 230: _is_concurrency_allowed when limit reached
# =============================================================================


class TestIsConcurrencyAllowed:
    """Lines 223-225: Concurrency limit reached → logs warning and returns False."""

    @pytest.mark.asyncio
    async def test_concurrency_not_reached_returns_true(self, memory_storage):
        """max_concurrent not reached → allowed."""
        engine = TriggerEngine()
        metadata = TriggerMetadata(source="test", config={}, max_concurrent=5)

        class FakeSaga:
            saga_name = "fake-saga"

        result = await engine._is_concurrency_allowed(metadata, FakeSaga)
        assert result is True

    @pytest.mark.asyncio
    async def test_concurrency_no_limit_always_allows(self):
        """Line 230: max_concurrent=None → always True."""
        engine = TriggerEngine()
        metadata = TriggerMetadata(source="test", config={}, max_concurrent=None)

        class FakeSaga:
            pass

        result = await engine._is_concurrency_allowed(metadata, FakeSaga)
        assert result is True

    @pytest.mark.asyncio
    async def test_concurrency_limit_reached_returns_false(self, memory_storage):
        """Lines 223-225: When running sagas >= max_concurrent → False + warning."""
        from sagaz.core.types import SagaStatus

        engine = TriggerEngine()

        class FakeSaga:
            saga_name = "limited-saga"

        # Store 3 executing sagas in memory storage
        for i in range(3):
            await memory_storage.save_saga_state(
                f"saga-exec-{i}",
                "limited-saga",
                SagaStatus.EXECUTING,
                [],
                {},
            )

        metadata = TriggerMetadata(source="test", config={}, max_concurrent=3)
        result = await engine._is_concurrency_allowed(metadata, FakeSaga)
        assert result is False  # Limit reached


# =============================================================================
# Lines 235-237, 242: _run_transformer with async transformer
# =============================================================================


class TestRunTransformerAsync:
    """Lines 235-237, 242: _run_transformer with async coroutine transformer."""

    @pytest.mark.asyncio
    async def test_run_transformer_async(self):
        """Lines 235-237: Async transformer awaited."""
        engine = TriggerEngine()

        class FakeSaga:
            async def on_event(self, payload):
                return {"transformed": payload["key"]}

        result = await engine._run_transformer(FakeSaga, "on_event", {"key": "value"})
        assert result == {"transformed": "value"}

    @pytest.mark.asyncio
    async def test_run_transformer_sync(self):
        """Line 242: sync transformer called normally."""
        engine = TriggerEngine()

        class FakeSaga:
            def on_event(self, payload):
                return {"processed": True}

        result = await engine._run_transformer(FakeSaga, "on_event", {"key": "val"})
        assert result == {"processed": True}

    @pytest.mark.asyncio
    async def test_run_transformer_returns_none(self):
        """Transformer returning None → result is None."""
        engine = TriggerEngine()

        class FakeSaga:
            async def on_event(self, payload):
                return None

        result = await engine._run_transformer(FakeSaga, "on_event", {})
        assert result is None


# =============================================================================
# Lines 250-252: _derive_saga_id when idempotency_key is set but value missing
# =============================================================================


class TestDeriveSagaIdMissingKey:
    """Lines 250-252: idempotency key declared but missing from payload → raises."""

    def test_derive_saga_id_missing_from_payload_raises(self):
        """Lines 250-252: IdempotencyKeyMissingInPayloadError raised."""
        from sagaz.core.exceptions import IdempotencyKeyMissingInPayloadError

        engine = TriggerEngine()

        class FakeSaga:
            pass

        metadata = TriggerMetadata(source="test", config={}, idempotency_key="required_field")

        with pytest.raises(IdempotencyKeyMissingInPayloadError):
            engine._derive_saga_id(metadata, {"other_field": "value"}, FakeSaga)


# =============================================================================
# Full integration: _process_trigger with non-dict transformer result (line 117)
# =============================================================================


class TestProcessTriggerNonDictContext:
    """Lines 117: Non-dict transformer result → trigger skipped."""

    @pytest.mark.asyncio
    async def test_non_dict_context_returns_none(self):
        """Lines 117, 120: If transformer returns non-dict, process returns None."""
        engine = TriggerEngine()

        class FakeSaga:
            __name__ = "FakeSaga"

        mock_trigger = MagicMock()
        mock_trigger.saga_class = FakeSaga
        mock_trigger.method_name = "on_event"
        mock_trigger.metadata = TriggerMetadata(source="test", config={})

        # Transformer returns a list (non-dict)
        with patch.object(
            engine, "_run_transformer", new_callable=AsyncMock, return_value=["not", "a", "dict"]
        ):
            result = await engine._process_trigger(mock_trigger, {"event": "data"})

        assert result is None


# =============================================================================
# Missing lines: 97, 202, 211-214, 223-225, 230, 235-237, 242, 250-252
# =============================================================================


class TestContextNoneAfterValidCheck:
    """Line 97: context = {} when context is None (defensive branch)."""

    @pytest.mark.asyncio
    async def test_context_none_set_to_empty_dict(self):
        """Line 97: _process_trigger reaches run_saga with context=None → {}."""
        engine = TriggerEngine()

        class FakeSaga:
            __name__ = "FakeSaga"
            saga_name = "FakeSaga"

        mock_trigger = MagicMock()
        mock_trigger.saga_class = FakeSaga
        mock_trigger.method_name = "on_event"
        mock_trigger.metadata = TriggerMetadata(
            source="test",
            config={},
            max_concurrent=100,
        )

        # Transformer returns a valid dict context but we'll override _is_valid_context
        with (
            patch.object(engine, "_run_transformer", new_callable=AsyncMock, return_value=None),
            patch.object(engine, "_is_valid_context", return_value=True),
            patch.object(
                engine, "_resolve_saga_id", new_callable=AsyncMock, return_value=("saga-123", True)
            ),
            patch.object(
                engine, "_is_concurrency_allowed", new_callable=AsyncMock, return_value=True
            ),
            patch.object(engine, "_run_saga", new_callable=AsyncMock) as mock_run,
        ):
            result = await engine._process_trigger(mock_trigger, {"event": "data"})

        # _run_saga called with empty dict (context was None → {})
        mock_run.assert_awaited_once_with(FakeSaga, "saga-123", {})
        assert result == "saga-123"


class TestExtractKeyValue:
    """Line 202: return None when key_logic is neither str nor callable."""

    def test_extract_key_value_non_string_non_callable(self):
        """Line 202: key_logic=42 returns None."""
        engine = TriggerEngine()
        result = engine._extract_key_value(42, {"key": "value"})
        assert result is None

    def test_extract_key_value_none_key_logic(self):
        """Line 202: key_logic=None returns None."""
        engine = TriggerEngine()
        result = engine._extract_key_value(None, {"key": "value"})
        assert result is None


class TestExtractStringKeyObjectPayload:
    """Lines 211-214: _extract_string_key with object payload."""

    def test_extract_from_object_with_attribute(self):
        """Lines 211-212: payload is object, attribute exists."""
        engine = TriggerEngine()

        class EventPayload:
            order_id = "ord-123"

        result = engine._extract_string_key("order_id", EventPayload())
        assert result == "ord-123"

    def test_extract_from_object_without_attribute(self):
        """Lines 213-214: payload is object without the attribute → None."""
        engine = TriggerEngine()

        class EventPayload:
            pass

        result = engine._extract_string_key("missing_key", EventPayload())
        assert result is None

    def test_extract_from_object_attribute_is_none(self):
        """Line 216: attribute exists but value is None → None."""
        engine = TriggerEngine()

        class EventPayload:
            order_id = None

        result = engine._extract_string_key("order_id", EventPayload())
        assert result is None


class TestExtractCallableKeyException:
    """Lines 223-225: _extract_callable_key exception handling."""

    def test_callable_raises_returns_none(self):
        """Lines 223-225: callable raises → returns None."""
        engine = TriggerEngine()

        def bad_extractor(payload):
            msg = "extraction failed"
            raise ValueError(msg)

        result = engine._extract_callable_key(bad_extractor, {"key": "val"})
        assert result is None


class TestCheckIdempotencyNoStorage:
    """Line 230: _check_idempotency returns False when no storage."""

    @pytest.mark.asyncio
    async def test_no_storage_returns_false(self):
        """Line 230: no storage → return False."""
        engine = TriggerEngine()
        mock_cfg = MagicMock()
        mock_cfg.storage = None
        with patch("sagaz.triggers.engine.get_config", return_value=mock_cfg):
            result = await engine._check_idempotency("saga-id", "MySaga")
        assert result is False


class TestCheckIdempotencyException:
    """Lines 235-237: _check_idempotency exception handling."""

    @pytest.mark.asyncio
    async def test_storage_exception_returns_false(self):
        """Lines 235-237: storage raises → return False."""
        engine = TriggerEngine()
        mock_storage = AsyncMock()
        mock_storage.load_saga_state = AsyncMock(side_effect=Exception("db error"))
        mock_cfg = MagicMock()
        mock_cfg.storage = mock_storage
        with patch("sagaz.triggers.engine.get_config", return_value=mock_cfg):
            result = await engine._check_idempotency("saga-id", "MySaga")
        assert result is False


class TestCheckConcurrencyNoStorage:
    """Line 242: _check_concurrency returns True when no storage."""

    @pytest.mark.asyncio
    async def test_no_storage_returns_true(self):
        """Line 242: no storage → return True."""
        engine = TriggerEngine()
        mock_cfg = MagicMock()
        mock_cfg.storage = None
        with patch("sagaz.triggers.engine.get_config", return_value=mock_cfg):
            result = await engine._check_concurrency("MySaga", 5)
        assert result is True


class TestCheckConcurrencyException:
    """Lines 250-252: _check_concurrency exception handling."""

    @pytest.mark.asyncio
    async def test_storage_exception_returns_true(self):
        """Lines 250-252: storage raises → return True (allow through)."""
        engine = TriggerEngine()
        mock_storage = AsyncMock()
        mock_storage.list_sagas = AsyncMock(side_effect=Exception("redis error"))
        mock_cfg = MagicMock()
        mock_cfg.storage = mock_storage
        with patch("sagaz.triggers.engine.get_config", return_value=mock_cfg):
            result = await engine._check_concurrency("MySaga", 5)
        assert result is True
