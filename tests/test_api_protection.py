"""
Tests for Unified Saga API - ensuring both declarative and imperative modes work,
and that mixing them is prevented.
"""

import pytest

from sagaz import Saga, action, compensate


# ============================================================================
# Test Declarative Mode
# ============================================================================


class SimpleSaga(Saga):
    """Test saga using declarative API with decorators."""

    saga_name = "simple-saga"

    @action("step1")
    async def step1(self, ctx):
        return {"value": 1}

    @compensate("step1")
    async def compensate_step1(self, ctx):
        pass


class TestDeclarativeMode:
    """Test that declarative mode (with decorators) works correctly."""

    @pytest.mark.asyncio
    async def test_run_works_on_declarative_saga(self):
        """run() should work normally on declarative Saga."""
        saga = SimpleSaga()
        result = await saga.run({})
        assert result.get("value") == 1

    def test_mode_is_declarative(self):
        """Saga with decorators should have mode='declarative'."""
        saga = SimpleSaga()
        assert saga._mode == 'declarative'

    def test_add_step_raises_on_declarative_saga(self):
        """add_step() should raise TypeError when saga has decorators."""
        saga = SimpleSaga()

        async def dummy_action(ctx):
            return {}

        with pytest.raises(TypeError) as exc_info:
            saga.add_step("new_step", dummy_action)

        error_message = str(exc_info.value)
        assert "Cannot use add_step()" in error_message
        assert "decorators" in error_message


# ============================================================================
# Test Imperative Mode
# ============================================================================


class TestImperativeMode:
    """Test that imperative mode (with add_step) works correctly."""

    @pytest.mark.asyncio
    async def test_add_step_works_on_fresh_saga(self):
        """add_step() should work on Saga without decorators."""

        async def action_fn(ctx):
            return {"result": "success"}

        saga = Saga(name="test-saga")
        saga.add_step("step1", action_fn)

        assert len(saga._steps) == 1
        assert saga._steps[0].step_id == "step1"

    def test_mode_is_imperative_after_add_step(self):
        """Saga should have mode='imperative' after add_step()."""

        async def action_fn(ctx):
            return {}

        saga = Saga(name="test-saga")
        assert saga._mode is None  # No mode yet

        saga.add_step("step1", action_fn)
        assert saga._mode == 'imperative'

    def test_add_step_returns_self_for_chaining(self):
        """add_step() should return self for method chaining."""

        async def action_fn(ctx):
            return {}

        saga = Saga(name="test-saga")
        result = saga.add_step("step1", action_fn)
        assert result is saga

    def test_method_chaining_works(self):
        """Method chaining with add_step should work."""

        async def step1(ctx):
            return {"a": 1}

        async def step2(ctx):
            return {"b": 2}

        saga = (
            Saga(name="chained")
            .add_step("step1", step1)
            .add_step("step2", step2, depends_on=["step1"])
        )

        assert len(saga._steps) == 2
        assert saga._steps[0].step_id == "step1"
        assert saga._steps[1].step_id == "step2"
        assert saga._steps[1].depends_on == ["step1"]

    @pytest.mark.asyncio
    async def test_run_works_on_imperative_saga(self):
        """run() should work on imperatively-built saga."""

        async def action_fn(ctx):
            return {"result": "success"}

        saga = Saga(name="test-saga")
        saga.add_step("step1", action_fn)
        result = await saga.run({})

        # Step results are merged directly into context
        assert result.get("result") == "success"
        # Step completion is tracked with __stepname_completed
        assert result.get("__step1_completed") is True

    def test_duplicate_step_name_raises_error(self):
        """Adding a step with duplicate name should raise ValueError."""

        async def action_fn(ctx):
            return {}

        saga = Saga(name="test-saga")
        saga.add_step("step1", action_fn)

        with pytest.raises(ValueError) as exc_info:
            saga.add_step("step1", action_fn)

        assert "already exists" in str(exc_info.value)


# ============================================================================
# Test Mode Protection (No Mixing)
# ============================================================================


class DecoratedSaga(Saga):
    saga_name = "decorated"

    @action("decorated_step")
    async def decorated_step(self, ctx):
        return {"decorated": True}


class TestModeMixingPrevention:
    """Test that you cannot mix declarative and imperative approaches."""

    def test_cannot_add_step_to_decorated_saga(self):
        """add_step() should fail on saga with decorators."""
        saga = DecoratedSaga()

        async def extra_step(ctx):
            return {}

        with pytest.raises(TypeError) as exc_info:
            saga.add_step("extra", extra_step)

        message = str(exc_info.value)
        assert "Cannot use add_step()" in message
        assert "decorators" in message.lower()


# ============================================================================
# Test Error Messages Are Helpful
# ============================================================================


class TestErrorMessages:
    """Test that error messages provide clear guidance."""

    def test_add_step_error_explains_alternatives(self):
        """Error should explain how to use declarative or imperative approach."""
        saga = DecoratedSaga()

        async def fn(ctx):
            return {}

        with pytest.raises(TypeError) as exc_info:
            saga.add_step("x", fn)

        message = str(exc_info.value)
        # Should mention decorators
        assert "@action" in message or "decorators" in message.lower()
        # Should explain the constraint
        assert "cannot" in message.lower() or "not" in message.lower()


# ============================================================================
# Test Backward Compatibility
# ============================================================================


class TestBackwardCompatibility:
    """Test that old code patterns still work."""

    @pytest.mark.asyncio
    async def test_declarative_saga_works(self):
        """Declarative pattern should work exactly as before."""

        class OldStyleSaga(Saga):
            saga_name = "old-style"

            @action("step")
            async def my_step(self, ctx):
                return {"old": "style"}

        saga = OldStyleSaga()
        result = await saga.run({})
        assert result.get("old") == "style"

    def test_saga_name_from_class_attribute(self):
        """saga_name class attribute should still work."""

        class NamedSaga(Saga):
            saga_name = "my-custom-name"

            @action("step")
            async def step(self, ctx):
                return {}

        saga = NamedSaga()
        assert saga.saga_name == "my-custom-name"

    def test_saga_name_from_constructor(self):
        """name parameter in constructor should work for imperative mode."""
        saga = Saga(name="constructor-name")
        assert saga.saga_name == "constructor-name"
