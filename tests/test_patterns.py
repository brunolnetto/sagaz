"""
Tests to cover remaining coverage gaps identified in the coverage report.

This file targets specific uncovered lines in:
- sagaz/monitoring/tracing.py (lines 206-223, 249, 254) - Span recording
- sagaz/compensation_graph.py (lines 285, 296-297, 304) - Cycle detection edge cases
- sagaz/decorators.py (lines 448-452) - Status branch coverage
- sagaz/core.py (lines 449-451) - Status branch coverage
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# ============================================
# CONSUMER INBOX TESTS (Correct API)
# ============================================


class TestConsumerInboxUnit:
    """Unit tests for ConsumerInbox class."""

    @pytest.mark.asyncio
    async def test_consumer_inbox_process_idempotent(self):
        """Test processing message with process_idempotent."""
        from unittest.mock import AsyncMock

        from sagaz.outbox.consumer_inbox import ConsumerInbox

        # Mock storage with required methods
        storage = AsyncMock()
        storage.check_and_insert_inbox = AsyncMock(return_value=False)  # Not a duplicate
        storage.update_inbox_duration = AsyncMock()

        inbox = ConsumerInbox(
            storage=storage,
            consumer_name="test-consumer",
        )

        # Handler passed to process_idempotent
        async def handler(msg: dict) -> str:
            return f"processed-{msg.get('id')}"

        # Process a message
        result = await inbox.process_idempotent(
            event_id="evt-001",
            source_topic="orders",
            event_type="OrderCreated",
            payload={"id": "123"},
            handler=handler,
        )

        assert result == "processed-123"
        storage.check_and_insert_inbox.assert_called_once()

    @pytest.mark.asyncio
    async def test_consumer_inbox_duplicate_detection(self):
        """Test that duplicate messages are detected."""
        from unittest.mock import AsyncMock

        from sagaz.outbox.consumer_inbox import ConsumerInbox

        # Mock storage that returns True (duplicate)
        storage = AsyncMock()
        storage.check_and_insert_inbox = AsyncMock(return_value=True)  # Is a duplicate

        inbox = ConsumerInbox(
            storage=storage,
            consumer_name="test-consumer",
        )

        async def handler(msg: dict) -> str:
            return "processed"

        # Process a duplicate message
        result = await inbox.process_idempotent(
            event_id="evt-dup",
            source_topic="orders",
            event_type="OrderCreated",
            payload={"id": "123"},
            handler=handler,
        )

        # Should return None for duplicates
        assert result is None


# ============================================
# OPTIMISTIC PUBLISHER TESTS (Correct API)
# ============================================


class TestOptimisticPublisherUnit:
    """Unit tests for OptimisticPublisher class."""

    @pytest.mark.asyncio
    async def test_optimistic_publisher_publish_after_commit_success(self):
        """Test successful publish with optimistic publisher."""
        from unittest.mock import AsyncMock

        from sagaz.outbox.optimistic_publisher import OptimisticPublisher
        from sagaz.outbox.types import OutboxEvent

        storage = AsyncMock()
        storage.mark_sent = AsyncMock()

        broker = AsyncMock()
        broker.publish = AsyncMock()

        publisher = OptimisticPublisher(storage=storage, broker=broker)

        event = OutboxEvent(
            saga_id="test-saga",
            event_type="order_created",
            payload={"order_id": "123"},
        )

        # Should publish successfully
        result = await publisher.publish_after_commit(event)

        assert result is True
        broker.publish.assert_called_once()
        storage.mark_sent.assert_called_once_with(event.event_id)

    @pytest.mark.asyncio
    async def test_optimistic_publisher_disabled(self):
        """Test that disabled publisher does not publish."""
        from unittest.mock import AsyncMock

        from sagaz.outbox.optimistic_publisher import OptimisticPublisher
        from sagaz.outbox.types import OutboxEvent

        storage = AsyncMock()
        broker = AsyncMock()

        publisher = OptimisticPublisher(storage=storage, broker=broker, enabled=False)

        event = OutboxEvent(
            saga_id="test-saga",
            event_type="order_created",
            payload={"order_id": "123"},
        )

        result = await publisher.publish_after_commit(event)

        assert result is False
        broker.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_optimistic_publisher_publish_failure(self):
        """Test that failed publish returns False."""
        from unittest.mock import AsyncMock

        from sagaz.outbox.optimistic_publisher import OptimisticPublisher
        from sagaz.outbox.types import OutboxEvent

        storage = AsyncMock()
        broker = AsyncMock()
        broker.publish = AsyncMock(side_effect=Exception("Broker error"))

        publisher = OptimisticPublisher(storage=storage, broker=broker)

        event = OutboxEvent(
            saga_id="test-saga",
            event_type="order_created",
            payload={"order_id": "456"},
        )

        # Should return False on failure
        result = await publisher.publish_after_commit(event)

        assert result is False


# ============================================
# TRACING SPAN RECORDING TESTS
# ============================================


class TestTracingSpanRecording:
    """Tests for tracing span recording methods that require mocked spans."""

    def test_record_saga_completion_not_recording(self):
        """Test record_saga_completion when span is not recording."""
        from sagaz.monitoring.tracing import SagaTracer
        from sagaz.types import SagaStatus

        tracer = SagaTracer("test-service")

        # Mock span that is not recording
        mock_span = MagicMock()
        mock_span.is_recording.return_value = False

        with patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", True):
            with patch("sagaz.monitoring.tracing.trace") as mock_trace:
                mock_trace.get_current_span.return_value = mock_span

                # Should not set attributes since not recording
                tracer.record_saga_completion(
                    saga_id="test-saga",
                    status=SagaStatus.COMPLETED,
                    completed_steps=3,
                    total_steps=3,
                    duration_ms=100.0,
                )

                # set_attributes should not be called when not recording
                mock_span.set_attributes.assert_not_called()

    def test_record_step_completion_failure_with_error(self):
        """Test record_step_completion for failed step with error."""
        from sagaz.monitoring.tracing import SagaTracer
        from sagaz.types import SagaStepStatus

        tracer = SagaTracer("test-service")

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        with patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", True):
            with patch("sagaz.monitoring.tracing.trace") as mock_trace:
                mock_trace.get_current_span.return_value = mock_span

                test_error = ValueError("Step failed")

                tracer.record_step_completion(
                    step_name="failing_step",
                    status=SagaStepStatus.FAILED,
                    duration_ms=50.0,
                    retry_count=2,
                    error=test_error,
                )

                # Should record exception
                mock_span.record_exception.assert_called_once_with(test_error)


# ============================================
# COMPENSATION GRAPH CYCLE DETECTION TESTS
# ============================================


class TestCompensationGraphCycleEdgeCases:
    """Tests for edge cases in cycle detection."""

    def test_find_cycle_with_already_visited_node(self):
        """Test _find_cycle when a node is already in visited set but not in path."""
        from sagaz.compensation_graph import SagaCompensationGraph

        graph = SagaCompensationGraph()

        async def noop(ctx):
            pass

        # Create a graph where DFS will visit a node, backtrack, then find it visited
        graph.register_compensation("a", noop)
        graph.register_compensation("b", noop, depends_on=["a"])
        graph.register_compensation("c", noop, depends_on=["a"])  # Both b and c depend on a

        # Mark all as executed
        graph.mark_step_executed("a")
        graph.mark_step_executed("b")
        graph.mark_step_executed("c")

        # This should not find a cycle - it's a valid DAG
        order = graph.get_compensation_order()
        assert len(order) >= 1

    def test_circular_dependency_raises_error(self):
        """Test that circular dependencies raise CircularDependencyError."""
        from sagaz.compensation_graph import (
            CircularDependencyError,
            SagaCompensationGraph,
        )

        graph = SagaCompensationGraph()

        async def noop(ctx):
            pass

        # Create a cycle: a -> b -> c -> a
        graph.register_compensation("a", noop, depends_on=["c"])
        graph.register_compensation("b", noop, depends_on=["a"])
        graph.register_compensation("c", noop, depends_on=["b"])

        graph.mark_step_executed("a")
        graph.mark_step_executed("b")
        graph.mark_step_executed("c")

        with pytest.raises(CircularDependencyError):
            graph.get_compensation_order()


# ============================================
# STATUS BRANCH COVERAGE TESTS (Using core.Saga correctly)
# ============================================


class TestStatusBranchCoverage:
    """Tests for 'compensating' status branches in core."""

    @pytest.mark.asyncio
    async def test_to_mermaid_with_execution_compensating_status(self):
        """Test Mermaid diagram with 'compensating' status."""
        from sagaz.core import Saga
        from sagaz.storage.memory import InMemorySagaStorage
        from sagaz.types import SagaStatus

        storage = InMemorySagaStorage()

        # Save saga with a step in 'compensating' status
        await storage.save_saga_state(
            saga_id="test-saga",
            saga_name="TestSaga",
            status=SagaStatus.COMPENSATING,
            steps=[
                {"name": "step1", "status": "completed"},
                {"name": "step2", "status": "compensating"},
                {"name": "step3", "status": "pending"},
            ],
            context={},
        )

        # Create saga and add steps using add_step method
        saga = Saga("TestSaga")
        saga._storage = storage

        async def step1(ctx):
            return {"data": "step1"}

        async def step2(ctx):
            return {"data": "step2"}

        async def step3(ctx):
            return {"data": "step3"}

        await saga.add_step("step1", step1)
        await saga.add_step("step2", step2)
        await saga.add_step("step3", step3)

        # Get mermaid diagram with execution
        diagram = await saga.to_mermaid_with_execution("test-saga", storage)

        # The diagram should be generated
        assert diagram is not None
        assert isinstance(diagram, str)


class TestDecoratorStatusBranches:
    """Tests for compensated status in diagrams."""

    @pytest.mark.asyncio
    async def test_saga_compensated_status_handling(self):
        """Test saga with compensated status."""
        from sagaz.core import Saga
        from sagaz.storage.memory import InMemorySagaStorage
        from sagaz.types import SagaStatus

        storage = InMemorySagaStorage()

        # Save a saga with compensated step status
        await storage.save_saga_state(
            saga_id="deco-saga",
            saga_name="TestDecoSaga",
            status=SagaStatus.COMPENSATING,
            steps=[
                {"name": "step1", "status": "compensated"},
            ],
            context={},
        )

        # Create saga
        my_saga = Saga("TestDecoSaga")
        my_saga._storage = storage

        async def step1(ctx):
            return "step1_result"

        await my_saga.add_step("step1", step1)

        # Get mermaid diagram - should handle compensated status
        diagram = await my_saga.to_mermaid_with_execution("deco-saga", storage)
        assert diagram is not None


# ============================================
# SETUP TRACING IMPORT ERROR TEST
# ============================================


class TestSetupTracingImportError:
    """Tests for setup_tracing when OTLP exporter import fails."""

    def test_setup_tracing_otlp_import_error(self):
        """Test setup_tracing gracefully handles OTLP import failure."""
        from sagaz.monitoring.tracing import setup_tracing

        # Mock TRACING_AVAILABLE as True but make OTLP import fail
        with patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", True):
            with patch.dict(
                sys.modules,
                {"opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None},
            ):
                # Should not raise, just skip OTLP configuration
                tracer = setup_tracing(
                    service_name="test-service",
                    endpoint="http://localhost:4317",
                )

                assert tracer is not None
                assert tracer.service_name == "test-service"


# ============================================
# TRACING UNAVAILABLE FALLBACK TESTS
# ============================================


class TestTracingUnavailableFallbacks:
    """Tests for tracing methods when TRACING_AVAILABLE is False."""

    def test_saga_tracer_no_tracing(self):
        """Test SagaTracer methods when tracing is unavailable."""
        with patch("sagaz.monitoring.tracing.TRACING_AVAILABLE", False):
            # Re-import to get fresh instance with TRACING_AVAILABLE=False
            from sagaz.monitoring import tracing
            from sagaz.types import SagaStatus, SagaStepStatus

            # Override the module-level flag
            original = tracing.TRACING_AVAILABLE
            tracing.TRACING_AVAILABLE = False

            try:
                tracer = tracing.SagaTracer("test-service")

                # All methods should be no-ops
                with tracer.start_saga_trace("saga-1", "TestSaga", 3) as span:
                    assert span is None

                with tracer.start_step_trace("saga-1", "TestSaga", "step1") as span:
                    assert span is None

                tracer.record_saga_completion(
                    saga_id="saga-1",
                    status=SagaStatus.COMPLETED,
                    completed_steps=3,
                    total_steps=3,
                    duration_ms=100.0,
                )

                tracer.record_step_completion(
                    step_name="step1",
                    status=SagaStepStatus.COMPLETED,
                    duration_ms=50.0,
                )

                ctx = tracer.get_trace_context()
                assert ctx == {}

                child_span = tracer.create_child_span("test-span")
                assert child_span is None

            finally:
                tracing.TRACING_AVAILABLE = original
