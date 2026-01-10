"""
Tests for compliance features.
"""

import pytest
from uuid import uuid4

from sagaz.core.compliance import (
    AccessLevel,
    ComplianceConfig,
    ComplianceManager,
)


class TestComplianceConfig:
    """Test compliance configuration"""

    def test_default_config(self):
        config = ComplianceConfig()

        assert config.enable_encryption is False
        assert config.enable_gdpr is False
        assert config.enable_access_control is False
        assert config.enable_audit_trail is True
        assert config.retention_days == 2555  # 7 years

    def test_custom_config(self):
        config = ComplianceConfig(
            enable_encryption=True,
            encryption_key="test-key",
            enable_gdpr=True,
            retention_days=365,
        )

        assert config.enable_encryption is True
        assert config.encryption_key == "test-key"
        assert config.enable_gdpr is True
        assert config.retention_days == 365


class TestEncryption:
    """Test context encryption"""

    def test_encrypt_sensitive_fields(self):
        config = ComplianceConfig(
            enable_encryption=True, encryption_key="secret-key-123"
        )
        manager = ComplianceManager(config)

        context = {
            "user_id": "12345",
            "payment_token": "tok_secret123",
            "amount": 100.00,
        }

        encrypted = manager.encrypt_context(context)

        # Non-sensitive fields unchanged
        assert encrypted["user_id"] == "12345"
        assert encrypted["amount"] == 100.00

        # Sensitive field encrypted
        assert encrypted["payment_token"] != "tok_secret123"
        assert encrypted["payment_token"]["_encrypted"] is True

    def test_decrypt_context(self):
        config = ComplianceConfig(
            enable_encryption=True, encryption_key="secret-key-123"
        )
        manager = ComplianceManager(config)

        original = {
            "user_id": "12345",
            "payment_token": "tok_secret123",
        }

        encrypted = manager.encrypt_context(original)
        decrypted = manager.decrypt_context(encrypted)

        assert decrypted["user_id"] == "12345"
        assert decrypted["payment_token"] == "tok_secret123"

    def test_encryption_disabled(self):
        config = ComplianceConfig(enable_encryption=False)
        manager = ComplianceManager(config)

        context = {"payment_token": "secret"}
        encrypted = manager.encrypt_context(context)

        # Should be unchanged when disabled
        assert encrypted == context

    def test_identify_sensitive_fields(self):
        config = ComplianceConfig()
        manager = ComplianceManager(config)

        # Test various sensitive keywords
        assert manager._is_sensitive("password") is True
        assert manager._is_sensitive("user_password") is True
        assert manager._is_sensitive("api_token") is True
        assert manager._is_sensitive("secret_key") is True
        assert manager._is_sensitive("credit_card") is True
        assert manager._is_sensitive("ssn") is True

        # Non-sensitive
        assert manager._is_sensitive("user_id") is False
        assert manager._is_sensitive("amount") is False
        assert manager._is_sensitive("status") is False


class TestAccessControl:
    """Test access control"""

    def test_access_control_disabled(self):
        config = ComplianceConfig(enable_access_control=False)
        manager = ComplianceManager(config)

        # All access allowed when disabled
        assert manager.check_access("user123", AccessLevel.READ) is True
        assert manager.check_access("user123", AccessLevel.ADMIN) is True

    def test_access_control_enabled(self):
        config = ComplianceConfig(
            enable_access_control=True,
            required_access_level=AccessLevel.READ,
        )
        manager = ComplianceManager(config)

        # For now, all access allowed (implement real checks in production)
        assert manager.check_access("user123", AccessLevel.READ) is True


class TestAuditTrail:
    """Test audit trail logging"""

    def test_create_audit_log(self):
        config = ComplianceConfig(enable_audit_trail=True)
        manager = ComplianceManager(config)

        saga_id = uuid4()
        log_entry = manager.create_audit_log(
            operation="replay",
            user_id="user123",
            saga_id=saga_id,
            details={"step": "payment", "override": True},
        )

        assert log_entry["operation"] == "replay"
        assert log_entry["user_id"] == "user123"
        assert log_entry["saga_id"] == str(saga_id)
        assert log_entry["details"]["step"] == "payment"
        assert "timestamp" in log_entry

    def test_audit_trail_disabled(self):
        config = ComplianceConfig(enable_audit_trail=False)
        manager = ComplianceManager(config)

        log_entry = manager.create_audit_log(
            operation="replay", user_id="user123", saga_id=uuid4()
        )

        assert log_entry == {}


class TestGDPRCompliance:
    """Test GDPR features"""

    @pytest.mark.asyncio
    async def test_delete_user_data_requires_gdpr_enabled(self):
        config = ComplianceConfig(enable_gdpr=False)
        manager = ComplianceManager(config)

        with pytest.raises(ValueError, match="GDPR features not enabled"):
            await manager.delete_user_data("user123", snapshot_storage=None)

    @pytest.mark.asyncio
    async def test_delete_user_data_gdpr_enabled(self):
        config = ComplianceConfig(enable_gdpr=True)
        manager = ComplianceManager(config)

        # Mock storage (None for now)
        deleted_count = await manager.delete_user_data(
            "user123",
            snapshot_storage=None,
            reason="User requested data deletion",
        )

        # Should return 0 for now (placeholder implementation)
        assert deleted_count == 0

    def test_anonymize_context(self):
        config = ComplianceConfig()
        manager = ComplianceManager(config)

        context = {
            "user_id": "12345",
            "payment_token": "tok_secret123",
            "amount": 100.00,
        }

        anonymized = manager.anonymize_context(context)

        # Non-sensitive unchanged
        assert anonymized["user_id"] == "12345"
        assert anonymized["amount"] == 100.00

        # Sensitive anonymized (hashed)
        assert anonymized["payment_token"] != "tok_secret123"
        assert len(anonymized["payment_token"]) == 16  # Hash length


class TestComplianceIntegration:
    """Integration tests with replay system"""

    def test_encrypt_decrypt_round_trip(self):
        """Test full encryption/decryption cycle"""
        config = ComplianceConfig(
            enable_encryption=True, encryption_key="production-key-123"
        )
        manager = ComplianceManager(config)

        # Simulate context from a saga
        original_context = {
            "order_id": "ORD-123",
            "user_email": "user@example.com",
            "payment_token": "tok_1234567890",
            "api_secret": "sk_live_secret123",
            "total_amount": 299.99,
        }

        # Encrypt before storing
        encrypted = manager.encrypt_context(original_context)

        # Verify sensitive fields are encrypted
        assert encrypted["payment_token"]["_encrypted"] is True
        assert encrypted["api_secret"]["_encrypted"] is True

        # Non-sensitive fields unchanged
        assert encrypted["order_id"] == "ORD-123"
        assert encrypted["total_amount"] == 299.99

        # Decrypt for authorized use
        decrypted = manager.decrypt_context(encrypted)

        # Verify complete round-trip
        assert decrypted == original_context

    def test_audit_trail_for_replay_operations(self):
        """Test audit logging for compliance"""
        config = ComplianceConfig(
            enable_audit_trail=True, log_all_operations=True
        )
        manager = ComplianceManager(config)

        saga_id = uuid4()

        # Log replay operation
        replay_log = manager.create_audit_log(
            operation="replay_from_checkpoint",
            user_id="admin@company.com",
            saga_id=saga_id,
            details={
                "checkpoint": "payment",
                "overrides": {"payment_token": "[REDACTED]"},
                "dry_run": False,
            },
        )

        assert replay_log["operation"] == "replay_from_checkpoint"
        assert replay_log["user_id"] == "admin@company.com"
        assert replay_log["details"]["checkpoint"] == "payment"

        # Log time-travel query
        query_log = manager.create_audit_log(
            operation="time_travel_query",
            user_id="analyst@company.com",
            saga_id=saga_id,
            details={"timestamp": "2024-01-15T10:30:00Z"},
        )

        assert query_log["operation"] == "time_travel_query"
