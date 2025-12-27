"""
Tests for high-priority features:
1. Optimistic Sending Pattern
2. Consumer Inbox Pattern
3. Kubernetes Manifests (validated via yaml parsing)
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from sagaz.outbox.consumer_inbox import ConsumerInbox
from sagaz.outbox.optimistic_publisher import OptimisticPublisher
from sagaz.outbox.types import OutboxEvent


class TestOptimisticPublisher:
    """Test optimistic sending pattern."""

    @pytest.fixture
    def mock_storage(self):
        """Mock outbox storage."""
        storage = Mock()
        storage.mark_sent = AsyncMock()
        return storage

    @pytest.fixture
    def mock_broker(self):
        """Mock message broker."""
        broker = Mock()
        broker.publish = AsyncMock()
        return broker

    @pytest.fixture
    def publisher(self, mock_storage, mock_broker):
        """Create optimistic publisher."""
        return OptimisticPublisher(
            storage=mock_storage, broker=mock_broker, enabled=True, timeout_seconds=0.5
        )

    @pytest.fixture
    def sample_event(self):
        """Create sample outbox event."""
        return OutboxEvent(
            saga_id="saga-123",
            event_type="OrderCreated",
            aggregate_type="order",
            aggregate_id="order-456",
            payload={"order_id": "order-456", "amount": 99.99},
            headers={"trace_id": "trace-789"},
        )

    async def test_optimistic_send_success(
        self, publisher, sample_event, mock_broker, mock_storage
    ):
        """Test successful optimistic send."""
        # Act
        result = await publisher.publish_after_commit(sample_event)

        # Assert
        assert result is True
        mock_broker.publish.assert_called_once()
        mock_storage.mark_sent.assert_called_once_with(sample_event.event_id)

    async def test_optimistic_send_disabled(self, mock_storage, mock_broker, sample_event):
        """Test optimistic send when disabled."""
        # Arrange
        publisher = OptimisticPublisher(storage=mock_storage, broker=mock_broker, enabled=False)

        # Act
        result = await publisher.publish_after_commit(sample_event)

        # Assert
        assert result is False
        mock_broker.publish.assert_not_called()
        mock_storage.mark_sent.assert_not_called()

    async def test_optimistic_send_timeout(
        self, publisher, sample_event, mock_broker, mock_storage
    ):
        """Test optimistic send timeout fallback."""

        # Arrange - make broker slow
        async def slow_publish(*args, **kwargs):
            await asyncio.sleep(1.0)  # Exceeds 0.5s timeout

        mock_broker.publish.side_effect = slow_publish

        # Act
        result = await publisher.publish_after_commit(sample_event)

        # Assert
        assert result is False  # Failed, will fallback to polling
        mock_storage.mark_sent.assert_not_called()

    async def test_optimistic_send_broker_error(
        self, publisher, sample_event, mock_broker, mock_storage
    ):
        """Test optimistic send broker error fallback."""
        # Arrange
        mock_broker.publish.side_effect = Exception("Broker connection refused")

        # Act
        result = await publisher.publish_after_commit(sample_event)

        # Assert
        assert result is False  # Failed, will fallback to polling
        mock_storage.mark_sent.assert_not_called()

    async def test_topic_resolution_default(self, publisher, sample_event):
        """Test default topic resolution."""
        topic = publisher._resolve_topic(sample_event)
        assert topic == "events.ordercreated"

    async def test_topic_resolution_custom_routing_key(self, publisher):
        """Test custom routing key takes precedence."""
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="OrderCreated",
            aggregate_type="order",
            aggregate_id="order-456",
            payload={},
            headers={"trace_id": "trace-789"},
            routing_key="custom.orders.created",
        )

        topic = publisher._resolve_topic(event)
        assert topic == "custom.orders.created"


class TestConsumerInbox:
    """Test consumer inbox pattern for exactly-once processing."""

    @pytest.fixture
    def mock_storage(self):
        """Mock storage with inbox support."""
        storage = Mock()
        storage.check_and_insert_inbox = AsyncMock(return_value=False)  # Not duplicate
        storage.update_inbox_duration = AsyncMock()
        storage.cleanup_inbox = AsyncMock(return_value=42)
        return storage

    @pytest.fixture
    def inbox(self, mock_storage):
        """Create consumer inbox."""
        return ConsumerInbox(storage=mock_storage, consumer_name="order-service")

    async def test_process_idempotent_new_event(self, inbox, mock_storage):
        """Test processing a new (non-duplicate) event."""
        # Arrange
        handler = AsyncMock(return_value={"processed": True})
        payload = {"order_id": "order-123"}

        # Act
        result = await inbox.process_idempotent(
            event_id="event-456",
            source_topic="orders",
            event_type="OrderCreated",
            payload=payload,
            handler=handler,
        )

        # Assert
        assert result == {"processed": True}
        handler.assert_called_once_with(payload)
        mock_storage.check_and_insert_inbox.assert_called_once()
        mock_storage.update_inbox_duration.assert_called_once()

    async def test_process_idempotent_duplicate_event(self, inbox, mock_storage):
        """Test processing a duplicate event (should skip)."""
        # Arrange
        mock_storage.check_and_insert_inbox.return_value = True  # Is duplicate
        handler = AsyncMock()

        # Act
        result = await inbox.process_idempotent(
            event_id="event-456",
            source_topic="orders",
            event_type="OrderCreated",
            payload={"order_id": "order-123"},
            handler=handler,
        )

        # Assert
        assert result is None  # Duplicate, not processed
        handler.assert_not_called()
        mock_storage.update_inbox_duration.assert_not_called()

    async def test_process_idempotent_handler_error(self, inbox, mock_storage):
        """Test handler exception propagates correctly."""
        # Arrange
        handler = AsyncMock(side_effect=ValueError("Invalid order"))

        # Act & Assert
        with pytest.raises(ValueError, match="Invalid order"):
            await inbox.process_idempotent(
                event_id="event-456",
                source_topic="orders",
                event_type="OrderCreated",
                payload={"order_id": "order-123"},
                handler=handler,
            )

    async def test_cleanup_old_entries(self, inbox, mock_storage):
        """Test cleanup of old inbox entries."""
        # Act
        deleted = await inbox.cleanup_old_entries(older_than_days=7)

        # Assert
        assert deleted == 42
        mock_storage.cleanup_inbox.assert_called_once_with(
            consumer_name="order-service", older_than_days=7
        )


@pytest.mark.integration  # K8s manifest tests are slow due to YAML parsing
class TestKubernetesManifests:
    """Test Kubernetes manifests are valid YAML."""

    def test_configmap_yaml_valid(self, k8s_manifests):
        """Test ConfigMap is valid YAML."""
        docs = k8s_manifests.get("k8s/configmap.yaml")
        if docs is None:
            pytest.skip("k8s/configmap.yaml not found")

        assert len(docs) == 2  # Namespace + ConfigMap
        assert docs[1]["kind"] == "ConfigMap"
        assert docs[1]["metadata"]["name"] == "outbox-worker-config"

    def test_outbox_worker_yaml_valid(self, k8s_manifests):
        """Test Outbox Worker deployment is valid YAML."""
        docs = k8s_manifests.get("k8s/outbox-worker.yaml")
        if docs is None:
            pytest.skip("k8s/outbox-worker.yaml not found")

        # Should have: Deployment, Service, ServiceAccount, PDB, HPA
        assert len(docs) == 5

        kinds = [doc["kind"] for doc in docs]
        assert "Deployment" in kinds
        assert "Service" in kinds
        assert "ServiceAccount" in kinds
        assert "PodDisruptionBudget" in kinds
        assert "HorizontalPodAutoscaler" in kinds

    def test_postgresql_yaml_valid(self, k8s_manifests):
        """Test PostgreSQL StatefulSet is valid YAML."""
        docs = k8s_manifests.get("k8s/postgresql.yaml")
        if docs is None:
            pytest.skip("k8s/postgresql.yaml not found")

        assert len(docs) == 3  # StatefulSet + 2 Services
        assert docs[0]["kind"] == "StatefulSet"
        assert docs[0]["metadata"]["name"] == "postgresql"

    def test_migration_job_yaml_valid(self, k8s_manifests):
        """Test Migration Job is valid YAML."""
        docs = k8s_manifests.get("k8s/migration-job.yaml")
        if docs is None:
            pytest.skip("k8s/migration-job.yaml not found")

        assert len(docs) == 1
        assert docs[0]["kind"] == "Job"
        assert docs[0]["metadata"]["name"] == "sagaz-migration"

    def test_prometheus_monitoring_yaml_valid(self, k8s_manifests):
        """Test Prometheus monitoring is valid YAML."""
        docs = k8s_manifests.get("k8s/prometheus-monitoring.yaml")
        if docs is None:
            pytest.skip("k8s/prometheus-monitoring.yaml not found")

        assert len(docs) == 2  # ServiceMonitor + PrometheusRule
        assert docs[0]["kind"] == "ServiceMonitor"
        assert docs[1]["kind"] == "PrometheusRule"

        # Check alerts are defined
        rules = docs[1]["spec"]["groups"][0]["rules"]
        alert_names = [rule["alert"] for rule in rules]
        assert "OutboxHighLag" in alert_names
        assert "OutboxWorkerDown" in alert_names
        assert "OutboxHighErrorRate" in alert_names


class TestIntegrationOptimisticAndInbox:
    """Integration tests for optimistic sending + consumer inbox."""

    async def test_end_to_end_flow(self):
        """Test complete flow: optimistic send → consume with inbox."""
        # This would be a full integration test with real PostgreSQL
        # For now, we verify the interfaces work together

        # Mock storage
        storage = Mock()
        storage.mark_sent = AsyncMock()
        storage.check_and_insert_inbox = AsyncMock(return_value=False)
        storage.update_inbox_duration = AsyncMock()

        # Mock broker
        broker = Mock()
        broker.publish = AsyncMock()

        # Create publisher and inbox
        publisher = OptimisticPublisher(storage, broker, enabled=True)
        inbox = ConsumerInbox(storage, "test-consumer")

        # Producer side: optimistic send
        event = OutboxEvent(
            saga_id="saga-123",
            event_type="TestEvent",
            aggregate_type="test",
            aggregate_id="test-123",
            payload={"data": "value"},
            headers={"trace_id": "trace-123"},
        )

        success = await publisher.publish_after_commit(event)
        assert success is True

        # Consumer side: process with inbox
        handler = AsyncMock(return_value={"processed": True})
        result = await inbox.process_idempotent(
            event_id=event.event_id,
            source_topic="test-topic",
            event_type="TestEvent",
            payload=event.payload,
            handler=handler,
        )

        assert result == {"processed": True}
        handler.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
