import pytest
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from sagaz.storage.manager import create_storage_manager, StorageManager

# Need to handle potential re-imports or module state if modules already loaded
# But since we are patching sys.modules, subsequent imports should see the mock

@pytest.mark.asyncio
async def test_create_storage_manager_explicit_backend():
    m1 = create_storage_manager(backend="memory")
    await m1.initialize()
    assert m1.saga is not None
    assert m1.outbox is not None

    m2 = create_storage_manager(backend="sqlite", url="sqlite://:memory:")
    await m2.initialize()
    assert m2.saga is not None
    await m2.close()

    with pytest.raises(ValueError):
        create_storage_manager(backend="postgresql")
        
    m3 = create_storage_manager(backend="postgresql", url="postgresql://loc/db")
    assert m3._saga_url == "postgresql://loc/db"

    m4 = create_storage_manager(backend="redis")
    assert m4._saga_url == "redis://localhost:6379"

    with pytest.raises(ValueError):
        create_storage_manager(backend="xyz")


@pytest.mark.asyncio
async def test_storage_manager_hybrid_mode():
    m = StorageManager(
        saga_url="memory://",
        outbox_url="sqlite://:memory:"
    )
    assert m.is_hybrid
    await m.initialize()
    assert m.saga.__class__.__name__ == "InMemorySagaStorage"
    assert m.outbox.__class__.__name__ == "SQLiteOutboxStorage"
    await m.close()


@pytest.mark.asyncio
async def test_initialize_unified_postgresql():
    mock_asyncpg = MagicMock()
    mock_pool = AsyncMock()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    
    # Configure pool.acquire() to return an async context manager
    mock_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=None)
    ))
    # Mock pool close methods - storage backends call await pool.close()
    mock_pool.close = AsyncMock()
    mock_pool.wait_closed = AsyncMock()
    
    # create_pool is a coroutine (async func in mock)
    mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
    
    # We patch sys.modules so 'import asyncpg' returns our mock
    with patch.dict(sys.modules, {"asyncpg": mock_asyncpg}):
        m = create_storage_manager("postgresql://user:pass@localhost/db")
        await m.initialize()
        
        assert m.saga is not None
        assert m.outbox is not None
        
        await m.close()
        # The storages call pool.close() directly (not via manager's shared pool logic)
        assert mock_pool.close.call_count >= 1


@pytest.mark.asyncio
async def test_initialize_unified_redis():
    # Create client mock - configure it properly without wait_closed
    mock_client = MagicMock(spec=['close', 'aclose', 'ping', 'get', 'set', 'delete', 'keys', 'scan'])
    mock_client.close = AsyncMock()
    mock_client.aclose = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)
    
    # Create redis.asyncio module mock with from_url returning our client
    mock_redis_asyncio = MagicMock()
    mock_redis_asyncio.from_url = MagicMock(return_value=mock_client)
    
    # Create parent redis module
    mock_redis = MagicMock()
    mock_redis.asyncio = mock_redis_asyncio
    
    # Patch both redis and redis.asyncio in sys.modules
    with patch.dict(sys.modules, {"redis": mock_redis, "redis.asyncio": mock_redis_asyncio}):
        m = create_storage_manager("redis://localhost:6379/0")
        await m.initialize()
        
        assert m.saga is not None
        assert m.outbox is not None
        
        await m.close()
        # Verify close or aclose was called
        assert mock_client.close.call_count + mock_client.aclose.call_count >= 1

@pytest.mark.asyncio
async def test_health_check_exceptions():
    m = StorageManager(url="memory://")
    await m.initialize()
    
    m.saga.health_check = AsyncMock(side_effect=Exception("Saga Error"))
    # Patching instance method
    
    health = await m.health_check()
    assert health["saga"]["status"] == "unhealthy"
    
    m.outbox.health_check = AsyncMock(side_effect=Exception("Outbox Error"))
    health = await m.health_check()
    assert health["outbox"]["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_create_storage_manager_unknown_url_scheme():
    with pytest.raises(ValueError, match="Cannot determine backend"):
        create_storage_manager("ftp://localhost")

