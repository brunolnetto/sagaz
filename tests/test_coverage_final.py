"""Final tests to push coverage to 95%+"""

from datetime import UTC

import pytest


class TestFinalCoverage:
    """Tests to cover remaining gaps"""

    @pytest.mark.asyncio
    async def test_outbox_types_from_dict(self):
        """Test OutboxEvent.from_dict method"""
        from datetime import datetime

        from sagaz.outbox.types import OutboxEvent, OutboxStatus

        event_dict = {
            "event_id": "evt-123",
            "saga_id": "saga-456",
            "aggregate_type": "order",
            "aggregate_id": "ord-789",
            "event_type": "OrderCreated",
            "payload": {"order_id": "123"},
            "headers": {"user": "test"},
            "status": "pending",
            "created_at": datetime.now(UTC).isoformat(),
            "claimed_at": None,
            "sent_at": None,
            "retry_count": 0,
            "last_error": None,
            "worker_id": None,
        }

        event = OutboxEvent.from_dict(event_dict)
        assert event.event_id == "evt-123"
        assert event.saga_id == "saga-456"
        assert event.status == OutboxStatus.PENDING

    @pytest.mark.asyncio
    async def test_state_machine_callbacks(self):
        """Test state machine optional callbacks"""
        from sagaz.core import Saga as ClassicSaga
        from sagaz.state_machine import SagaStateMachine

        saga = ClassicSaga(name="TestSaga")
        sm = SagaStateMachine(saga)

        # Test callbacks that are no-ops
        await sm.on_start()
        await sm.on_succeed()
        await sm.on_fail()

    @pytest.mark.asyncio
    async def test_compensation_graph_reset(self):
        """Test compensation graph reset_execution"""
        from sagaz.compensation_graph import SagaCompensationGraph

        graph = SagaCompensationGraph()

        async def comp_fn(ctx):
            pass

        graph.register_compensation("step1", comp_fn)
        graph.mark_step_executed("step1")

        assert len(graph.executed_steps) == 1

        # Reset should clear executed steps
        graph.reset_execution()
        assert len(graph.executed_steps) == 0

    def test_broker_factory_get_available(self):
        """Test get_available_brokers function"""
        from sagaz.outbox.brokers.factory import get_available_brokers

        brokers = get_available_brokers()

        # Memory broker should always be available
        assert "memory" in brokers
        assert isinstance(brokers, list)

    def test_storage_factory_get_available(self):
        """Test get_available_backends function"""
        from sagaz.storage.factory import get_available_backends

        backends = get_available_backends()

        # Memory backend should always be available
        assert "memory" in backends
        assert backends["memory"]["available"] is True

    @pytest.mark.asyncio
    async def test_compensation_graph_unexecuted_steps(self):
        """Test compensation graph with unexecuted steps"""
        from sagaz.compensation_graph import SagaCompensationGraph

        graph = SagaCompensationGraph()

        async def comp_fn(ctx):
            pass

        # Register steps but don't mark as executed
        graph.register_compensation("step1", comp_fn)
        graph.register_compensation("step2", comp_fn)

        # Get compensation order for unexecuted steps should return empty
        order = graph.get_compensation_order()
        assert order == []

    @pytest.mark.asyncio
    async def test_broker_factory_unknown_type(self):
        """Test broker factory with unknown type"""
        from sagaz.outbox.brokers.factory import create_broker

        with pytest.raises(ValueError, match="Unknown broker type"):
            create_broker("unknown")

    @pytest.mark.asyncio
    async def test_state_machine_step_lifecycle(self):
        """Test step state machine lifecycle"""
        from sagaz.state_machine import SagaStepStateMachine

        sm = SagaStepStateMachine(step_name="test_step")

        # Activate initial state for async state machine
        await sm.activate_initial_state()

        # Test state transitions
        assert sm.current_state.id == "pending"

        await sm.start()
        assert sm.current_state.id == "executing"

        await sm.succeed()
        assert sm.current_state.id == "completed"

        await sm.compensate()
        assert sm.current_state.id == "compensating"

        await sm.compensation_success()
        assert sm.current_state.id == "compensated"

    @pytest.mark.asyncio
    async def test_worker_batch_processing(self):
        """Test worker process_batch method"""
