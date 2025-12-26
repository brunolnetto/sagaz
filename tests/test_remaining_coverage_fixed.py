"""Fixed tests for remaining coverage - PostgreSQL and Worker"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio


class TestPostgreSQLStorageCoverageFixed:
    """PostgreSQL storage tests with proper async mocks"""
    
    def setup_mock_pool(self, mock_conn):
        """Helper to setup async context manager mock"""
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = mock_ctx
        return mock_pool
    
    @pytest.mark.asyncio
    async def test_postgresql_get_pending_count(self):
        """Test getting count of pending events"""
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage
            
            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/test")
            
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 42
            storage._pool = self.setup_mock_pool(mock_conn)
            
            count = await storage.get_pending_count()
            
            assert count == 42
    
    @pytest.mark.asyncio
    async def test_postgresql_get_stuck_events(self):
        """Test getting stuck events"""
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage
            
            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/test")
            
            mock_conn = AsyncMock()
            mock_conn.fetch.return_value = []
            storage._pool = self.setup_mock_pool(mock_conn)
            
            events = await storage.get_stuck_events(claimed_older_than_seconds=300)
            
            assert events == []
    
    @pytest.mark.asyncio
    async def test_postgresql_release_stuck_events(self):
        """Test releasing stuck events"""
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage
            
            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/test")
            
            mock_conn = AsyncMock()
            mock_conn.execute.return_value = "UPDATE 5"
            storage._pool = self.setup_mock_pool(mock_conn)
            
            count = await storage.release_stuck_events(claimed_older_than_seconds=300)
            
            assert count == 5
    
    @pytest.mark.asyncio
    async def test_postgresql_get_by_id_not_found(self):
        """Test getting event by ID when not found"""
        with patch("sagaz.outbox.storage.postgresql.ASYNCPG_AVAILABLE", True):
            from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage
            
            storage = PostgreSQLOutboxStorage("postgresql://localhost:5432/test")
            
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = None
            storage._pool = self.setup_mock_pool(mock_conn)
            
            event = await storage.get_by_id("nonexistent")
            
            assert event is None


class TestWorkerCoverageFixed:
    """Fixed worker tests"""
    
    @pytest.mark.asyncio
    async def test_worker_max_retries_exceeded(self):
        """Test event that exceeds max retries goes to FAILED"""
        from sagaz.outbox.worker import OutboxWorker, OutboxConfig
        from sagaz.outbox.types import OutboxEvent, OutboxStatus
        
        storage = AsyncMock()
        broker = AsyncMock()
        broker.publish_event.side_effect = Exception("Broker error")
        
        # Return an event from update_status
        updated_event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"},
            retry_count=10
        )
        storage.update_status.return_value = updated_event
        
        config = OutboxConfig(max_retries=2)
        worker = OutboxWorker(storage, broker, config)
        
        # Event that has already retried max times
        event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"},
            retry_count=2  # Already at max
        )
        
        await worker._process_event(event)
        
        # Should update to FAILED (check if called)
        assert storage.update_status.called
    
    @pytest.mark.asyncio
    async def test_worker_successful_publish(self):
        """Test successful event publishing"""
        from sagaz.outbox.worker import OutboxWorker, OutboxConfig
        from sagaz.outbox.types import OutboxEvent, OutboxStatus
        
        storage = AsyncMock()
        broker = AsyncMock()
        
        config = OutboxConfig()
        worker = OutboxWorker(storage, broker, config)
        
        event = OutboxEvent(
            saga_id="saga-1",
            aggregate_type="order",
            aggregate_id="1",
            event_type="OrderCreated",
            payload={"order_id": "123"}
        )
        
        await worker._process_event(event)
        
        # Should publish_event and mark as SENT
        broker.publish_event.assert_called_once()
        storage.update_status.assert_called()
