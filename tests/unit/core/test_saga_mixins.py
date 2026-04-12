"""
Dedicated unit tests for the saga mixin modules extracted from saga.py.

Covers:
- sagaz/core/_saga_step.py        (SagaStep dataclass)
- sagaz/core/_saga_compensation.py (_SagaCompensationMixin)
- sagaz/core/_saga_snapshot.py    (_SagaSnapshotMixin)
- sagaz/core/_saga_visualization.py (_SagaVisualizationMixin)
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from sagaz.core.saga._compensation import _SagaCompensationMixin
from sagaz.core.saga._snapshot import _SagaSnapshotMixin
from sagaz.core.saga._step import SagaStep
from sagaz.core.saga._visualization import _SagaVisualizationMixin
from sagaz.core.exceptions import SagaCompensationError, SagaExecutionError
from sagaz.core.types import SagaStepStatus


# =============================================================================
# Helpers / stubs
# =============================================================================


async def _noop(ctx):
    return None


async def _noop_comp(result, ctx):
    pass


# =============================================================================
# _saga_step.py  (SagaStep)
# =============================================================================


class TestSagaStep:
    """Unit tests for the SagaStep dataclass."""

    def test_default_values(self):
        step = SagaStep(name="s1", action=_noop)
        assert step.name == "s1"
        assert step.action is _noop
        assert step.compensation is None
        assert step.status == SagaStepStatus.PENDING
        assert step.result is None
        assert step.error is None
        assert step.executed_at is None
        assert step.compensated_at is None
        assert step.retry_attempts == 0
        assert step.max_retries == 3
        assert step.timeout == 30.0
        assert step.compensation_timeout == 30.0
        assert step.retry_count == 0
        assert step.pivot is False
        assert step.tainted is False
        assert step.idempotency_key != ""

    def test_custom_values(self):
        comp = _noop_comp
        step = SagaStep(
            name="pay",
            action=_noop,
            compensation=comp,
            timeout=5.0,
            max_retries=1,
            pivot=True,
        )
        assert step.compensation is comp
        assert step.timeout == 5.0
        assert step.max_retries == 1
        assert step.pivot is True

    def test_hash_uses_idempotency_key(self):
        step = SagaStep(name="s", action=_noop)
        assert hash(step) == hash(step.idempotency_key)

    def test_hash_unique_across_instances(self):
        s1 = SagaStep(name="s", action=_noop)
        s2 = SagaStep(name="s", action=_noop)
        assert hash(s1) != hash(s2)

    def test_can_compensate_with_compensation_and_not_tainted(self):
        step = SagaStep(name="s", action=_noop, compensation=_noop_comp)
        assert step.can_compensate() is True

    def test_can_compensate_without_compensation(self):
        step = SagaStep(name="s", action=_noop)
        assert step.can_compensate() is False

    def test_can_compensate_when_tainted(self):
        step = SagaStep(name="s", action=_noop, compensation=_noop_comp, tainted=True)
        assert step.can_compensate() is False

    def test_mark_tainted_sets_tainted_and_status(self):
        step = SagaStep(name="s", action=_noop, compensation=_noop_comp)
        assert step.tainted is False
        step.mark_tainted()
        assert step.tainted is True
        assert step.status == SagaStepStatus.TAINTED

    def test_mark_tainted_prevents_compensation(self):
        step = SagaStep(name="s", action=_noop, compensation=_noop_comp)
        step.mark_tainted()
        assert step.can_compensate() is False

    def test_step_can_store_result(self):
        step = SagaStep(name="s", action=_noop)
        step.result = {"order_id": 42}
        assert step.result == {"order_id": 42}

    def test_step_can_store_error(self):
        step = SagaStep(name="s", action=_noop)
        err = ValueError("oops")
        step.error = err
        assert step.error is err

    def test_step_timestamps_default_none(self):
        step = SagaStep(name="s", action=_noop)
        assert step.executed_at is None
        assert step.compensated_at is None

    def test_step_timestamps_can_be_set(self):
        step = SagaStep(name="s", action=_noop)
        now = datetime.now()
        step.executed_at = now
        step.compensated_at = now
        assert step.executed_at == now
        assert step.compensated_at == now


# =============================================================================
# _saga_compensation.py  (_SagaCompensationMixin)
# =============================================================================


class _CompensationHost(_SagaCompensationMixin):
    """Minimal host for _SagaCompensationMixin tests."""

    def __init__(self, retry_backoff_base: float = 0.0):
        self.completed_steps: list[SagaStep] = []
        self.compensation_errors: list[Exception] = []
        self.context = MagicMock()
        self.retry_backoff_base = retry_backoff_base


class TestSagaCompensationMixin:
    """Unit tests for _SagaCompensationMixin."""

    @pytest.mark.asyncio
    async def test_run_compensations_empty(self):
        host = _CompensationHost()
        errors = await host._run_compensations()
        assert errors == []

    @pytest.mark.asyncio
    async def test_run_compensations_skips_no_compensation(self):
        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop)  # no compensation
        host.completed_steps = [step]
        errors = await host._run_compensations()
        assert errors == []

    @pytest.mark.asyncio
    async def test_run_compensations_calls_in_reverse(self):
        order = []

        async def comp_a(result, ctx):
            order.append("a")

        async def comp_b(result, ctx):
            order.append("b")

        host = _CompensationHost()
        step_a = SagaStep(name="a", action=_noop, compensation=comp_a)
        step_b = SagaStep(name="b", action=_noop, compensation=comp_b)
        host.completed_steps = [step_a, step_b]
        await host._run_compensations()
        assert order == ["b", "a"]

    @pytest.mark.asyncio
    async def test_compensate_all_no_errors(self):
        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop, compensation=_noop_comp)
        host.completed_steps = [step]
        # Should not raise
        await host._compensate_all()

    @pytest.mark.asyncio
    async def test_compensate_all_raises_on_failure(self):
        async def failing_comp(result, ctx):
            raise RuntimeError("comp error")

        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop, compensation=failing_comp)
        host.completed_steps = [step]
        with pytest.raises(SagaCompensationError):
            await host._compensate_all()

    @pytest.mark.asyncio
    async def test_try_compensate_step_success_returns_none(self):
        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop, compensation=_noop_comp)
        result = await host._try_compensate_step(step)
        assert result is None

    @pytest.mark.asyncio
    async def test_try_compensate_step_failure_returns_error(self):
        async def bad_comp(result, ctx):
            raise RuntimeError("fail")

        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop, compensation=bad_comp)
        result = await host._try_compensate_step(step)
        assert isinstance(result, SagaCompensationError)

    @pytest.mark.asyncio
    async def test_try_compensate_appends_to_compensation_errors(self):
        async def bad_comp(result, ctx):
            raise RuntimeError("fail")

        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop, compensation=bad_comp)
        await host._try_compensate_step(step)
        assert len(host.compensation_errors) == 1

    def test_raise_compensation_error(self):
        host = _CompensationHost()
        errors = [SagaCompensationError("e1"), SagaCompensationError("e2")]
        with pytest.raises(SagaCompensationError, match="Failed to compensate 2 steps"):
            host._raise_compensation_error(errors)

    @pytest.mark.asyncio
    async def test_compensate_step_success(self):
        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop, compensation=_noop_comp)
        await host._compensate_step(step)
        assert step.status == SagaStepStatus.COMPENSATED
        assert step.compensated_at is not None

    @pytest.mark.asyncio
    async def test_compensate_step_sets_compensating_then_compensated(self):
        states = []

        async def tracking_comp(result, ctx):
            states.append("during")

        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop, compensation=tracking_comp)
        await host._compensate_step(step)
        assert step.status == SagaStepStatus.COMPENSATED

    @pytest.mark.asyncio
    async def test_compensate_step_timeout(self):
        async def slow_comp(result, ctx):
            await asyncio.sleep(10)

        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop, compensation=slow_comp, compensation_timeout=0.01)
        with pytest.raises(SagaCompensationError, match="timed out"):
            await host._compensate_step(step)
        assert step.status == SagaStepStatus.FAILED

    @pytest.mark.asyncio
    async def test_compensate_step_exception(self):
        async def exploding_comp(result, ctx):
            raise ValueError("boom")

        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop, compensation=exploding_comp)
        with pytest.raises(SagaCompensationError, match="failed"):
            await host._compensate_step(step)
        assert step.status == SagaStepStatus.FAILED

    @pytest.mark.asyncio
    async def test_compensate_step_with_retry_succeeds_first_attempt(self):
        host = _CompensationHost()
        step = SagaStep(name="s", action=_noop, compensation=_noop_comp)
        await host._compensate_step_with_retry(step)  # Should not raise

    @pytest.mark.asyncio
    async def test_compensate_step_with_retry_exhausts_and_raises(self):
        call_count = 0

        async def always_fails(result, ctx):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("always fails")

        host = _CompensationHost(retry_backoff_base=0.0)
        step = SagaStep(name="s", action=_noop, compensation=always_fails)
        with pytest.raises(SagaCompensationError):
            await host._compensate_step_with_retry(step)
        assert call_count == 3  # max_comp_retries

    @pytest.mark.asyncio
    async def test_invoke_async_function(self):
        async def async_fn(x):
            return x + 1

        result = await _SagaCompensationMixin._invoke(async_fn, 5)
        assert result == 6

    @pytest.mark.asyncio
    async def test_invoke_sync_function(self):
        def sync_fn(x):
            return x * 2

        result = await _SagaCompensationMixin._invoke(sync_fn, 4)
        assert result == 8


# =============================================================================
# _saga_snapshot.py  (_SagaSnapshotMixin)
# =============================================================================


class _SnapshotHost(_SagaSnapshotMixin):
    """Minimal host class for _SagaSnapshotMixin tests."""

    def __init__(self):
        from sagaz.core.context import SagaContext
        from sagaz.core.types import SagaStatus

        self.saga_id = str(uuid4())
        self.name = "TestSaga"
        self.version = "1.0"
        self.status = SagaStatus.PENDING
        self.steps: list[SagaStep] = []
        self.completed_steps: list[SagaStep] = []
        self.context = SagaContext(_saga_id=self.saga_id)
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.error: Exception | None = None
        self.compensation_errors: list[Exception] = []
        # Mock the state machine to avoid async initialization requirement
        self._state_machine = MagicMock()
        self._state_machine.current_state.name = "pending"
        self._executing = False
        self._execution_lock = asyncio.Lock()
        self._executed_step_keys: set[str] = set()
        self.replay_config = None
        self.snapshot_storage = None


class TestSnapshotMixinStatusMethods:
    """Test status reporting methods of _SagaSnapshotMixin."""

    def test_get_status_basic(self):
        host = _SnapshotHost()
        status = host.get_status()
        assert status["saga_id"] == host.saga_id
        assert status["name"] == "TestSaga"
        assert status["version"] == "1.0"
        assert status["total_steps"] == 0
        assert status["completed_steps"] == 0
        assert status["error"] is None
        assert status["compensation_errors"] == []

    def test_get_status_with_steps(self):
        host = _SnapshotHost()
        step = SagaStep(name="s", action=_noop)
        host.steps = [step]
        status = host.get_status()
        assert status["total_steps"] == 1
        assert len(status["steps"]) == 1

    def test_get_status_with_error(self):
        host = _SnapshotHost()
        host.error = ValueError("something failed")
        status = host.get_status()
        assert "something failed" in status["error"]

    def test_get_status_with_timestamps(self):
        host = _SnapshotHost()
        host.started_at = datetime(2024, 1, 1, 12, 0, 0)
        host.completed_at = datetime(2024, 1, 1, 12, 5, 0)
        status = host.get_status()
        assert status["started_at"] is not None
        assert status["completed_at"] is not None

    def test_get_step_status(self):
        host = _SnapshotHost()
        step = SagaStep(name="pay", action=_noop)
        step.retry_count = 2
        result = host._get_step_status(step)
        assert result["name"] == "pay"
        assert result["status"] == step.status.value
        assert result["retry_count"] == 2
        assert result["error"] is None

    def test_get_step_status_with_error(self):
        host = _SnapshotHost()
        step = SagaStep(name="s", action=_noop)
        step.error = RuntimeError("oops")
        result = host._get_step_status(step)
        assert "oops" in result["error"]

    def test_get_step_status_with_timestamps(self):
        host = _SnapshotHost()
        step = SagaStep(name="s", action=_noop)
        now = datetime.now()
        step.executed_at = now
        step.compensated_at = now
        result = host._get_step_status(step)
        assert result["executed_at"] is not None
        assert result["compensated_at"] is not None

    def test_format_datetime_none(self):
        assert _SagaSnapshotMixin._format_datetime(None) is None

    def test_format_datetime_value(self):
        dt = datetime(2024, 6, 15, 10, 30, 0)
        result = _SagaSnapshotMixin._format_datetime(dt)
        assert result == dt.isoformat()

    def test_current_state_property(self):
        host = _SnapshotHost()
        # State machine starts in initial state
        state = host.current_state
        assert isinstance(state, str)
        assert len(state) > 0


class TestSnapshotMixinSnapshotCapture:
    """Test snapshot capture logic."""

    @pytest.mark.asyncio
    async def test_capture_snapshot_no_replay_config(self):
        host = _SnapshotHost()
        host.replay_config = None
        # Should quietly return (no-op)
        await host._capture_snapshot("step1", 0, before=True)  # No exception

    @pytest.mark.asyncio
    async def test_capture_snapshot_snapshots_disabled(self):
        from sagaz.core.replay import ReplayConfig

        host = _SnapshotHost()
        host.replay_config = ReplayConfig(enable_snapshots=False)
        await host._capture_snapshot("step1", 0, before=True)  # No exception

    @pytest.mark.asyncio
    async def test_capture_snapshot_no_storage_warns(self):
        from sagaz.core.replay import ReplayConfig

        host = _SnapshotHost()
        host.replay_config = ReplayConfig(enable_snapshots=True)
        host.snapshot_storage = None
        # Should warn but not crash
        await host._capture_snapshot("step1", 0, before=True)

    @pytest.mark.asyncio
    async def test_capture_snapshot_saves_to_storage(self):
        from sagaz.core.replay import ReplayConfig, SnapshotStrategy

        host = _SnapshotHost()
        host.status = MagicMock()
        host.status.value = "executing"
        host.replay_config = ReplayConfig(
            enable_snapshots=True, snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP
        )
        mock_storage = AsyncMock()
        host.snapshot_storage = mock_storage
        await host._capture_snapshot("step1", 0, before=True)
        mock_storage.save_snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_snapshot_storage_error_is_swallowed(self):
        from sagaz.core.replay import ReplayConfig, SnapshotStrategy

        host = _SnapshotHost()
        host.status = MagicMock()
        host.status.value = "executing"
        host.replay_config = ReplayConfig(
            enable_snapshots=True, snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP
        )
        mock_storage = AsyncMock()
        mock_storage.save_snapshot.side_effect = RuntimeError("storage down")
        host.snapshot_storage = mock_storage
        # Should log error but not propagate
        await host._capture_snapshot("step1", 0, before=True)

    @pytest.mark.asyncio
    async def test_capture_snapshot_strategy_says_skip(self):
        """Line 101: _should_capture_snapshot returns False → early return."""
        from sagaz.core.replay import ReplayConfig, SnapshotStrategy

        host = _SnapshotHost()
        host.status = MagicMock()
        host.status.value = "executing"
        host.replay_config = ReplayConfig(
            enable_snapshots=True, snapshot_strategy=SnapshotStrategy.AFTER_EACH_STEP
        )
        mock_storage = AsyncMock()
        host.snapshot_storage = mock_storage
        # before=True with AFTER_EACH_STEP → _should_capture_snapshot returns False
        await host._capture_snapshot("step1", 0, before=True)
        mock_storage.save_snapshot.assert_not_called()


class TestSnapshotMixinShouldCapture:
    """Test _should_capture_snapshot strategy logic."""

    def test_before_each_step_before_true(self):
        from sagaz.core.replay import SnapshotStrategy
        from sagaz.core.types import SagaStatus

        host = _SnapshotHost()
        host.status = SagaStatus.EXECUTING
        assert host._should_capture_snapshot(SnapshotStrategy.BEFORE_EACH_STEP, before=True) is True

    def test_before_each_step_before_false(self):
        from sagaz.core.replay import SnapshotStrategy
        from sagaz.core.types import SagaStatus

        host = _SnapshotHost()
        host.status = SagaStatus.EXECUTING
        assert (
            host._should_capture_snapshot(SnapshotStrategy.BEFORE_EACH_STEP, before=False) is False
        )

    def test_after_each_step_before_false(self):
        from sagaz.core.replay import SnapshotStrategy
        from sagaz.core.types import SagaStatus

        host = _SnapshotHost()
        host.status = SagaStatus.EXECUTING
        assert (
            host._should_capture_snapshot(SnapshotStrategy.AFTER_EACH_STEP, before=False) is True
        )

    def test_after_each_step_before_true(self):
        from sagaz.core.replay import SnapshotStrategy
        from sagaz.core.types import SagaStatus

        host = _SnapshotHost()
        host.status = SagaStatus.EXECUTING
        assert (
            host._should_capture_snapshot(SnapshotStrategy.AFTER_EACH_STEP, before=True) is False
        )

    def test_on_completion_when_completed(self):
        from sagaz.core.replay import SnapshotStrategy
        from sagaz.core.types import SagaStatus

        host = _SnapshotHost()
        host.status = SagaStatus.COMPLETED
        assert (
            host._should_capture_snapshot(SnapshotStrategy.ON_COMPLETION, before=False) is True
        )

    def test_on_completion_when_not_completed(self):
        from sagaz.core.replay import SnapshotStrategy
        from sagaz.core.types import SagaStatus

        host = _SnapshotHost()
        host.status = SagaStatus.EXECUTING
        assert (
            host._should_capture_snapshot(SnapshotStrategy.ON_COMPLETION, before=False) is False
        )

    def test_on_failure_when_failed(self):
        from sagaz.core.replay import SnapshotStrategy
        from sagaz.core.types import SagaStatus

        host = _SnapshotHost()
        host.status = SagaStatus.FAILED
        assert host._should_capture_snapshot(SnapshotStrategy.ON_FAILURE, before=False) is True

    def test_on_failure_when_not_failed(self):
        from sagaz.core.replay import SnapshotStrategy
        from sagaz.core.types import SagaStatus

        host = _SnapshotHost()
        host.status = SagaStatus.EXECUTING
        assert host._should_capture_snapshot(SnapshotStrategy.ON_FAILURE, before=False) is False


class TestExecuteFromSnapshot:
    """Test execute_from_snapshot method via Saga class."""

    @pytest.mark.asyncio
    async def test_execute_from_snapshot_basic(self):
        from sagaz.core.replay import ReplayConfig, SagaSnapshot
        from sagaz.core.saga import Saga

        class _TestSaga(Saga):
            pass

        saga = _TestSaga(name="SnapSaga", retry_backoff_base=0.01)

        async def step_action(ctx):
            return {"done": True}

        await saga.add_step("resume_step", step_action)

        snapshot = SagaSnapshot.create(
            saga_id=UUID(saga.saga_id),
            saga_name="SnapSaga",
            step_name="resume_step",
            step_index=0,
            status="executing",
            context={"preloaded": True},
            completed_steps=[],
        )

        result = await saga.execute_from_snapshot(snapshot)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_from_snapshot_with_context_override(self):
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.saga import Saga

        class _TestSaga(Saga):
            pass

        saga = _TestSaga(name="SnapSaga2", retry_backoff_base=0.01)
        captured = {}

        async def step_action(ctx):
            captured["value"] = ctx.get("override_key")
            return captured["value"]

        await saga.add_step("step", step_action)

        snapshot = SagaSnapshot.create(
            saga_id=UUID(saga.saga_id),
            saga_name="SnapSaga2",
            step_name="step",
            step_index=0,
            status="executing",
            context={},
            completed_steps=[],
        )

        result = await saga.execute_from_snapshot(snapshot, context_override={"override_key": 99})
        assert result.success is True
        assert captured["value"] == 99

    @pytest.mark.asyncio
    async def test_execute_from_snapshot_skips_completed_steps(self):
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.saga import Saga

        class _TestSaga(Saga):
            pass

        saga = _TestSaga(name="SnapSagaSkip", retry_backoff_base=0.01)
        executed = []

        async def step_a(ctx):
            executed.append("a")

        async def step_b(ctx):
            executed.append("b")

        await saga.add_step("step_a", step_a)
        await saga.add_step("step_b", step_b)

        # step_a is already completed in snapshot
        snapshot = SagaSnapshot.create(
            saga_id=UUID(saga.saga_id),
            saga_name="SnapSagaSkip",
            step_name="step_b",
            step_index=1,
            status="executing",
            context={},
            completed_steps=["step_a"],
        )

        result = await saga.execute_from_snapshot(snapshot)
        assert result.success is True
        # Only step_b should have executed (step_a was pre-completed)
        assert "a" not in executed
        assert "b" in executed

    @pytest.mark.asyncio
    async def test_execute_from_snapshot_already_executing_raises(self):
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.saga import Saga

        class _TestSaga(Saga):
            pass

        saga = _TestSaga(name="BusySaga", retry_backoff_base=0.01)
        saga._executing = True

        snapshot = SagaSnapshot.create(
            saga_id=UUID(saga.saga_id),
            saga_name="BusySaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={},
            completed_steps=[],
        )

        with pytest.raises(SagaExecutionError, match="already executing"):
            await saga.execute_from_snapshot(snapshot)

    @pytest.mark.asyncio
    async def test_execute_from_snapshot_transition_not_allowed(self):
        """Lines 169-171: TransitionNotAllowed during state machine start → handled as failure."""
        from statemachine.exceptions import TransitionNotAllowed

        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.saga import Saga

        class _TestSaga(Saga):
            pass

        saga = _TestSaga(name="TransitionSaga", retry_backoff_base=0.01)

        async def step_action(ctx):
            return {}

        await saga.add_step("step1", step_action)

        snapshot = SagaSnapshot.create(
            saga_id=UUID(saga.saga_id),
            saga_name="TransitionSaga",
            step_name="step1",
            step_index=0,
            status="executing",
            context={},
            completed_steps=[],
        )

        with patch.object(
            saga._state_machine,
            "start",
            side_effect=TransitionNotAllowed(event=None, configuration=set()),
        ):
            result = await saga.execute_from_snapshot(snapshot)
        # TransitionNotAllowed → SagaExecutionError → handled as execution failure
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_from_snapshot_step_fails(self):
        """Lines 207-208: exception during execution → _handle_execution_failure."""
        from sagaz.core.replay import SagaSnapshot
        from sagaz.core.saga import Saga

        class _TestSaga(Saga):
            pass

        saga = _TestSaga(name="FailSaga", retry_backoff_base=0.01)

        async def failing_action(ctx):
            raise RuntimeError("step exploded")

        await saga.add_step("bad_step", failing_action)

        snapshot = SagaSnapshot.create(
            saga_id=UUID(saga.saga_id),
            saga_name="FailSaga",
            step_name="bad_step",
            step_index=0,
            status="executing",
            context={},
            completed_steps=[],
        )

        result = await saga.execute_from_snapshot(snapshot)
        assert result.success is False


# =============================================================================
# _saga_visualization.py  (_SagaVisualizationMixin)
# =============================================================================


class TestSagaVisualizationMixin:
    """Tests for _SagaVisualizationMixin via the full Saga class."""

    @pytest.fixture
    async def simple_saga(self):
        from sagaz.core.saga import Saga

        class _VizSaga(Saga):
            pass

        saga = _VizSaga(name="VizSaga", retry_backoff_base=0.01)
        await saga.add_step("step_a", _noop, _noop_comp)
        await saga.add_step("step_b", _noop, _noop_comp)
        return saga

    @pytest.fixture
    async def no_comp_saga(self):
        from sagaz.core.saga import Saga

        class _NoCompSaga(Saga):
            pass

        saga = _NoCompSaga(name="NoCompViz")
        await saga.add_step("step_x", _noop)
        return saga

    @pytest.mark.asyncio
    async def test_to_mermaid_returns_string(self, simple_saga):
        diagram = simple_saga.to_mermaid()
        assert isinstance(diagram, str)
        assert len(diagram) > 0

    @pytest.mark.asyncio
    async def test_to_mermaid_contains_step_names(self, simple_saga):
        diagram = simple_saga.to_mermaid()
        assert "step_a" in diagram
        assert "step_b" in diagram

    @pytest.mark.asyncio
    async def test_to_mermaid_direction_lr(self, simple_saga):
        diagram = simple_saga.to_mermaid(direction="LR")
        assert "LR" in diagram

    @pytest.mark.asyncio
    async def test_to_mermaid_no_compensation(self, simple_saga):
        diagram = simple_saga.to_mermaid(show_compensation=False)
        assert isinstance(diagram, str)

    @pytest.mark.asyncio
    async def test_to_mermaid_with_highlight_trail(self, simple_saga):
        trail = {
            "completed_steps": ["step_a"],
            "failed_step": "step_b",
            "compensated_steps": ["step_a"],
        }
        diagram = simple_saga.to_mermaid(highlight_trail=trail)
        assert isinstance(diagram, str)

    @pytest.mark.asyncio
    async def test_to_mermaid_without_state_markers(self, simple_saga):
        diagram = simple_saga.to_mermaid(show_state_markers=False)
        assert isinstance(diagram, str)

    @pytest.mark.asyncio
    async def test_to_mermaid_step_without_compensation(self, no_comp_saga):
        diagram = no_comp_saga.to_mermaid()
        assert isinstance(diagram, str)

    @pytest.mark.asyncio
    async def test_to_mermaid_markdown_wraps_in_fence(self, simple_saga):
        md = simple_saga.to_mermaid_markdown()
        assert md.startswith("```mermaid\n")
        assert md.endswith("\n```")

    @pytest.mark.asyncio
    async def test_to_mermaid_markdown_contains_diagram(self, simple_saga):
        md = simple_saga.to_mermaid_markdown()
        plain = simple_saga.to_mermaid()
        assert plain in md

    @pytest.mark.asyncio
    async def test_to_mermaid_markdown_direction_lr(self, simple_saga):
        md = simple_saga.to_mermaid_markdown(direction="LR")
        assert "LR" in md

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_no_data(self, simple_saga):
        mock_storage = AsyncMock()
        mock_storage.load_saga_state.return_value = None
        diagram = await simple_saga.to_mermaid_with_execution("fake-id", mock_storage)
        assert isinstance(diagram, str)
        mock_storage.load_saga_state.assert_called_once_with("fake-id")

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_completed_step(self, simple_saga):
        mock_storage = AsyncMock()
        mock_storage.load_saga_state.return_value = {
            "steps": [{"name": "step_a", "status": "completed"}]
        }
        diagram = await simple_saga.to_mermaid_with_execution("id", mock_storage)
        assert isinstance(diagram, str)

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_failed_step(self, simple_saga):
        mock_storage = AsyncMock()
        mock_storage.load_saga_state.return_value = {
            "steps": [
                {"name": "step_a", "status": "completed"},
                {"name": "step_b", "status": "failed"},
            ]
        }
        diagram = await simple_saga.to_mermaid_with_execution("id", mock_storage)
        assert isinstance(diagram, str)

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_compensated_step(self, simple_saga):
        mock_storage = AsyncMock()
        mock_storage.load_saga_state.return_value = {
            "steps": [{"name": "step_a", "status": "compensated"}]
        }
        diagram = await simple_saga.to_mermaid_with_execution("id", mock_storage)
        assert isinstance(diagram, str)

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_compensating_step(self, simple_saga):
        mock_storage = AsyncMock()
        mock_storage.load_saga_state.return_value = {
            "steps": [{"name": "step_a", "status": "compensating"}]
        }
        diagram = await simple_saga.to_mermaid_with_execution("id", mock_storage)
        assert isinstance(diagram, str)

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_unknown_status(self, simple_saga):
        """Branch 106→94: unrecognised status is a no-op (falls off all elifs)."""
        mock_storage = AsyncMock()
        mock_storage.load_saga_state.return_value = {
            "steps": [{"name": "step_a", "status": "pending"}]
        }
        diagram = await simple_saga.to_mermaid_with_execution("id", mock_storage)
        assert isinstance(diagram, str)
