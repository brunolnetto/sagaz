"""
Tests for Saga Time-Travel functionality.

Tests querying historical state at specific timestamps.
"""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sagaz.core.replay import SagaSnapshot
from sagaz.core.time_travel import SagaTimeTravel, HistoricalState
from sagaz.storage.backends.memory_snapshot import InMemorySnapshotStorage


class TestHistoricalState:
    """Test HistoricalState data structure"""

    def test_to_dict(self):
        saga_id = uuid4()
        timestamp = datetime.now(timezone.utc)
        
        state = HistoricalState(
            saga_id=saga_id,
            saga_name="TestSaga",
            timestamp=timestamp,
            status="executing",
            context={"key": "value"},
            completed_steps=["step1"],
            current_step="step2",
            step_index=1,
        )

        result = state.to_dict()

        assert result["saga_id"] == str(saga_id)
        assert result["saga_name"] == "TestSaga"
        assert result["status"] == "executing"
        assert result["context"] == {"key": "value"}
        assert result["completed_steps"] == ["step1"]
        assert result["current_step"] == "step2"
        assert result["step_index"] == 1


class TestSagaTimeTravel:
    """Test time-travel query functionality"""

    @pytest.fixture
    def storage(self):
        return InMemorySnapshotStorage()

    @pytest.fixture
    def saga_id(self):
        return uuid4()

    @pytest.fixture
    async def sample_snapshots(self, storage, saga_id):
        """Create sample snapshots at different times"""
        base_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

        snapshots = []
        for i in range(3):
            snapshot = SagaSnapshot.create(
                saga_id=saga_id,
                saga_name="TestSaga",
                step_name=f"step{i+1}",
                step_index=i,
                status="executing",
                context={
                    "step_count": i + 1,
                    "data": f"value_{i+1}",
                },
                completed_steps=[f"step{j+1}" for j in range(i)],
            )
            # Manually set created_at for testing
            snapshot.created_at = base_time + timedelta(minutes=i * 10)
            await storage.save_snapshot(snapshot)
            snapshots.append(snapshot)

        return snapshots

    @pytest.mark.asyncio
    async def test_get_state_at_exact_snapshot_time(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        # Query at exact snapshot time
        target_time = sample_snapshots[1].created_at
        state = await time_travel.get_state_at(target_time)

        assert state is not None
        assert state.saga_id == saga_id
        assert state.saga_name == "TestSaga"
        assert state.current_step == "step2"
        assert state.step_index == 1
        assert state.context["step_count"] == 2
        assert state.completed_steps == ["step1"]

    @pytest.mark.asyncio
    async def test_get_state_at_between_snapshots(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        # Query between snapshot 1 and 2
        target_time = sample_snapshots[0].created_at + timedelta(minutes=5)
        state = await time_travel.get_state_at(target_time)

        # Should return state from snapshot 1 (latest before target)
        assert state is not None
        assert state.current_step == "step1"
        assert state.step_index == 0
        assert state.context["step_count"] == 1

    @pytest.mark.asyncio
    async def test_get_state_at_before_first_snapshot(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        # Query before any snapshots exist
        target_time = sample_snapshots[0].created_at - timedelta(minutes=5)
        state = await time_travel.get_state_at(target_time)

        assert state is None

    @pytest.mark.asyncio
    async def test_get_state_at_after_last_snapshot(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        # Query after last snapshot
        target_time = sample_snapshots[-1].created_at + timedelta(hours=1)
        state = await time_travel.get_state_at(target_time)

        # Should return state from last snapshot
        assert state is not None
        assert state.current_step == "step3"
        assert state.step_index == 2
        assert state.context["step_count"] == 3

    @pytest.mark.asyncio
    async def test_get_state_at_naive_timestamp_converted_to_utc(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        # Use naive timestamp (no timezone)
        target_time = datetime(2024, 1, 1, 10, 15, 0)  # No tzinfo
        state = await time_travel.get_state_at(target_time)

        assert state is not None

    @pytest.mark.asyncio
    async def test_list_state_changes_all(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        states = await time_travel.list_state_changes()

        assert len(states) == 3
        # Should be in chronological order
        assert states[0].current_step == "step1"
        assert states[1].current_step == "step2"
        assert states[2].current_step == "step3"

    @pytest.mark.asyncio
    async def test_list_state_changes_with_after_filter(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        # Filter: only states after 10:05
        after_time = sample_snapshots[0].created_at + timedelta(minutes=5)
        states = await time_travel.list_state_changes(after=after_time)

        assert len(states) == 2
        assert states[0].current_step == "step2"
        assert states[1].current_step == "step3"

    @pytest.mark.asyncio
    async def test_list_state_changes_with_before_filter(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        # Filter: only states before 10:15
        before_time = sample_snapshots[1].created_at + timedelta(minutes=5)
        states = await time_travel.list_state_changes(before=before_time)

        assert len(states) == 2
        assert states[0].current_step == "step1"
        assert states[1].current_step == "step2"

    @pytest.mark.asyncio
    async def test_list_state_changes_with_limit(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        states = await time_travel.list_state_changes(limit=2)

        assert len(states) == 2
        assert states[0].current_step == "step1"
        assert states[1].current_step == "step2"

    @pytest.mark.asyncio
    async def test_get_context_at_specific_key(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        target_time = sample_snapshots[1].created_at
        value = await time_travel.get_context_at(target_time, key="data")

        assert value == "value_2"

    @pytest.mark.asyncio
    async def test_get_context_at_all_keys(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        target_time = sample_snapshots[1].created_at
        context = await time_travel.get_context_at(target_time)

        assert context == {"step_count": 2, "data": "value_2"}

    @pytest.mark.asyncio
    async def test_get_context_at_nonexistent_time(
        self, storage, saga_id, sample_snapshots
    ):
        time_travel = SagaTimeTravel(saga_id=saga_id, snapshot_storage=storage)

        target_time = sample_snapshots[0].created_at - timedelta(hours=1)
        context = await time_travel.get_context_at(target_time)

        assert context is None


class TestTimeTravelIntegration:
    """Integration tests with actual saga execution"""

    @pytest.mark.asyncio
    async def test_time_travel_with_real_saga_snapshots(self):
        """Test time-travel with snapshots from actual saga execution"""
        from sagaz.core.replay import ReplayConfig, SnapshotStrategy
        from tests.integration.test_saga_replay_integration import SimpleSagaForReplay

        storage = InMemorySnapshotStorage()
        config = ReplayConfig(
            enable_snapshots=True,
            snapshot_strategy=SnapshotStrategy.BEFORE_EACH_STEP,
        )

        # Execute saga to create snapshots
        saga = SimpleSagaForReplay(replay_config=config, snapshot_storage=storage)
        await saga.build()
        saga.context.set("initial_data", "test_value")
        result = await saga.execute()

        assert result.success is True

        # Use time-travel to query historical state
        from uuid import UUID
        time_travel = SagaTimeTravel(
            saga_id=UUID(saga.saga_id),
            snapshot_storage=storage,
        )

        # List all state changes
        states = await time_travel.list_state_changes()
        assert len(states) >= 3  # At least 3 steps

        # Query state at beginning
        first_state = states[0]
        assert first_state.current_step == "step1"
        assert len(first_state.completed_steps) == 0

        # Query state in middle
        mid_state = states[1]
        assert mid_state.current_step == "step2"
        assert "step1" in mid_state.completed_steps

        # Verify context was preserved
        for state in states:
            assert "initial_data" in state.context
            assert state.context["initial_data"] == "test_value"
