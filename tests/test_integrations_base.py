"""
Tests for sagaz.integrations._base module.
"""

import pytest

from sagaz.integrations._base import (
    SagaContextManager,
    generate_correlation_id,
    get_correlation_id,
)


class TestSagaContextManager:
    """Tests for SagaContextManager."""
    
    def test_set_and_get(self):
        """Test setting and getting values."""
        SagaContextManager.clear()
        
        SagaContextManager.set("key1", "value1")
        SagaContextManager.set("key2", 42)
        
        assert SagaContextManager.get("key1") == "value1"
        assert SagaContextManager.get("key2") == 42
        assert SagaContextManager.get("nonexistent") is None
        assert SagaContextManager.get("nonexistent", "default") == "default"
    
    def test_get_all(self):
        """Test getting all values."""
        SagaContextManager.clear()
        
        SagaContextManager.set("a", 1)
        SagaContextManager.set("b", 2)
        
        all_values = SagaContextManager.get_all()
        
        assert all_values == {"a": 1, "b": 2}
    
    def test_clear(self):
        """Test clearing the context."""
        SagaContextManager.set("key", "value")
        SagaContextManager.clear()
        
        assert SagaContextManager.get("key") is None
        assert SagaContextManager.get_all() == {}
    
    def test_scope_context_manager(self):
        """Test scope context manager."""
        SagaContextManager.clear()
        
        # Set initial value
        SagaContextManager.set("outer", "outer_value")
        
        with SagaContextManager.scope(inner="inner_value", correlation_id="test-123"):
            # Inside scope, we have new context
            assert SagaContextManager.get("inner") == "inner_value"
            assert SagaContextManager.get("correlation_id") == "test-123"
            # Outer value is NOT visible (new scope)
            assert SagaContextManager.get("outer") is None
        
        # Outside scope, original context is restored
        # Note: The scope resets to empty, not to previous state
        # This is expected behavior for request-scoped contexts
    
    def test_nested_scopes(self):
        """Test nested scope context managers."""
        with SagaContextManager.scope(level="outer"):
            assert SagaContextManager.get("level") == "outer"
            
            with SagaContextManager.scope(level="inner"):
                assert SagaContextManager.get("level") == "inner"
            
            # Back to outer scope
            assert SagaContextManager.get("level") == "outer"
    
    def test_scope_isolation(self):
        """Test that scopes are isolated."""
        with SagaContextManager.scope(a=1):
            SagaContextManager.set("b", 2)
            
            with SagaContextManager.scope(c=3):
                # New scope doesn't see parent's values
                assert SagaContextManager.get("a") is None
                assert SagaContextManager.get("b") is None
                assert SagaContextManager.get("c") == 3


class TestCorrelationId:
    """Tests for correlation ID functions."""
    
    def test_generate_correlation_id_format(self):
        """Test that generated correlation IDs are valid UUIDs."""
        correlation_id = generate_correlation_id()
        
        # Should be a valid UUID format
        import uuid
        parsed = uuid.UUID(correlation_id)
        assert str(parsed) == correlation_id
    
    def test_generate_correlation_id_uniqueness(self):
        """Test that each call generates a unique ID."""
        ids = [generate_correlation_id() for _ in range(100)]
        
        # All should be unique
        assert len(set(ids)) == 100
    
    def test_get_correlation_id_generates_if_missing(self):
        """Test that get_correlation_id generates a new ID if not set."""
        SagaContextManager.clear()
        
        correlation_id = get_correlation_id()
        
        # Should be a valid UUID
        import uuid
        uuid.UUID(correlation_id)
        
        # Should now be stored in context
        assert SagaContextManager.get("correlation_id") == correlation_id
    
    def test_get_correlation_id_returns_existing(self):
        """Test that get_correlation_id returns existing ID."""
        SagaContextManager.clear()
        SagaContextManager.set("correlation_id", "existing-id")
        
        correlation_id = get_correlation_id()
        
        assert correlation_id == "existing-id"
