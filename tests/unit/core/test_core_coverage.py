"""
Tests to cover missing lines in core modules:
- sagaz/core/logger.py (NullLogger methods + configure_default_logging)
- sagaz/core/compliance.py (edge cases: no key, GDPR, audit disabled)
- sagaz/core/env.py (substitute paths, substitute_dict, get_env/load_env)
"""

import importlib
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest


# =============================================================================
# logger.py - missing: 30, 36, 42, 45, 104, 107-108
# =============================================================================


class TestNullLoggerAllMethods:
    """Cover all NullLogger method bodies."""

    def test_null_logger_debug(self):
        from sagaz.core.logger import NullLogger

        nl = NullLogger()
        nl.debug("debug message")  # covers line 30

    def test_null_logger_info(self):
        from sagaz.core.logger import NullLogger

        nl = NullLogger()
        nl.info("info message")  # covers line 36

    def test_null_logger_warning(self):
        from sagaz.core.logger import NullLogger

        nl = NullLogger()
        nl.warning("warning message")  # covers line 42

    def test_null_logger_error(self):
        from sagaz.core.logger import NullLogger

        nl = NullLogger()
        nl.error("error message")  # covers line 45

    def test_null_logger_exception(self):
        from sagaz.core.logger import NullLogger

        nl = NullLogger()
        nl.exception("exception message")

    def test_null_logger_critical(self):
        from sagaz.core.logger import NullLogger

        nl = NullLogger()
        nl.critical("critical message")


class TestConfigureDefaultLogging:
    """Cover configure_default_logging function."""

    def test_configure_default_logging_default_args(self):
        import logging

        from sagaz.core.logger import configure_default_logging

        configure_default_logging()  # covers lines 104, 107-108
        sagaz_logger = logging.getLogger("sagaz")
        assert sagaz_logger.level == logging.INFO

    def test_configure_default_logging_custom_level(self):
        import logging

        from sagaz.core.logger import configure_default_logging

        configure_default_logging(level=logging.DEBUG)
        sagaz_logger = logging.getLogger("sagaz")
        assert sagaz_logger.level == logging.DEBUG

        # Reset to INFO
        configure_default_logging(level=logging.INFO)


# =============================================================================
# compliance.py - missing: 98-99, 118, 148, 162, 172-174
# =============================================================================


class TestEncryptContextEdgeCases:
    """Cover compliance encrypt/decrypt edge cases."""

    def test_encrypt_context_enabled_but_no_key(self):
        """Lines 98-99: warning when enable_encryption=True but encryption_key=None."""
        from sagaz.core.compliance import ComplianceConfig, ComplianceManager

        config = ComplianceConfig(enable_encryption=True, encryption_key=None)
        manager = ComplianceManager(config)

        context = {"payment_token": "tok_secret", "user_id": "123"}
        # Should log warning and return context unchanged
        result = manager.encrypt_context(context)
        assert result == context  # returned unchanged

    def test_decrypt_context_non_encrypted_field(self):
        """Line 118: else branch for non-encrypted field in decrypt_context."""
        from sagaz.core.compliance import ComplianceConfig, ComplianceManager

        config = ComplianceConfig(enable_encryption=True, encryption_key="test-key")
        manager = ComplianceManager(config)

        # Mix of encrypted and plain fields
        context = {
            "user_id": "123",  # non-sensitive, not encrypted
            "payment_token": {
                "_encrypted": True,
                "_value": manager._simple_encrypt("tok_secret"),
            },
        }
        decrypted = manager.decrypt_context(context)
        assert decrypted["user_id"] == "123"  # covers the else branch (line 118)
        assert decrypted["payment_token"] == "tok_secret"


class TestCheckAccessEnabled:
    """Line 148: check_access body when enable_access_control=True."""

    def test_check_access_with_control_enabled(self):
        from sagaz.core.compliance import AccessLevel, ComplianceConfig, ComplianceManager

        config = ComplianceConfig(
            enable_access_control=True,
            required_access_level=AccessLevel.READ,
        )
        manager = ComplianceManager(config)

        # Should execute the logger.info line (line 148)
        result = manager.check_access("user123", AccessLevel.REPLAY)
        assert result is True

    def test_check_access_no_required_level_uses_default(self):
        from sagaz.core.compliance import AccessLevel, ComplianceConfig, ComplianceManager

        config = ComplianceConfig(
            enable_access_control=True,
            required_access_level=AccessLevel.ADMIN,
        )
        manager = ComplianceManager(config)

        # None → uses config default
        result = manager.check_access("user123", required_level=None)
        assert result is True


class TestDeleteUserData:
    """Line 162: delete_user_data when GDPR enabled."""

    @pytest.mark.asyncio
    async def test_delete_user_data_gdpr_disabled_raises(self):
        """Line 162 area: ValueError when GDPR not enabled."""
        from sagaz.core.compliance import ComplianceConfig, ComplianceManager

        config = ComplianceConfig(enable_gdpr=False)
        manager = ComplianceManager(config)

        mock_storage = object()
        with pytest.raises(ValueError, match="GDPR features not enabled"):
            await manager.delete_user_data("user123", mock_storage)

    @pytest.mark.asyncio
    async def test_delete_user_data_gdpr_enabled(self):
        """Line 162-163 path: logger.warning when GDPR enabled."""
        from sagaz.core.compliance import ComplianceConfig, ComplianceManager

        config = ComplianceConfig(enable_gdpr=True)
        manager = ComplianceManager(config)

        mock_storage = object()
        result = await manager.delete_user_data("user123", mock_storage)
        assert result == 0


class TestCreateAuditLogDisabled:
    """Lines 172-174: create_audit_log returns {} when audit_trail disabled."""

    def test_create_audit_log_disabled(self):
        from sagaz.core.compliance import ComplianceConfig, ComplianceManager

        config = ComplianceConfig(enable_audit_trail=False)
        manager = ComplianceManager(config)

        log_entry = manager.create_audit_log(
            operation="replay",
            user_id="user123",
            saga_id=uuid4(),
        )
        assert log_entry == {}  # covers lines 172-174


# =============================================================================
# env.py - missing: 18-19, 237-238, 263-264, 274-275, 350-353
# =============================================================================


class TestEnvSubstitutePaths:
    """Cover substitute and substitute_dict missing branches."""

    def test_substitute_required_var_present(self):
        """Lines 237-238: ${VAR:?error} when var IS set (returns value, not raises)."""
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        os.environ["REQUIRED_TEST_VAR"] = "my_value"
        try:
            result = env.substitute("${REQUIRED_TEST_VAR:?This is required}")
            assert result == "my_value"  # covers the return path at line 237
        finally:
            del os.environ["REQUIRED_TEST_VAR"]

    def test_substitute_dict_nested_dict(self):
        """Lines 263-264: substitute_dict recurses into nested dicts."""
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        os.environ["NESTED_HOST"] = "db.example.com"
        try:
            data = {
                "database": {
                    "host": "${NESTED_HOST}",
                    "port": "5432",
                }
            }
            result = env.substitute_dict(data)
            assert result["database"]["host"] == "db.example.com"
        finally:
            del os.environ["NESTED_HOST"]

    def test_substitute_dict_list_with_non_string_item(self):
        """Lines 274-275: list items that are neither str nor dict are kept as-is."""
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        data = {
            "ports": [8080, 8443, "9090"],  # int items are kept as-is (line 274-275)
        }
        result = env.substitute_dict(data)
        assert 8080 in result["ports"]
        assert 8443 in result["ports"]


class TestGetEnvLoadEnv:
    """Lines 350-353: get_env() and load_env() global functions."""

    def test_get_env_returns_instance(self):
        """Line 350: global EnvManager is created and returned."""
        from sagaz.core import env as env_module

        # Reset the global instance
        env_module._global_env = None

        from sagaz.core.env import get_env

        result = get_env()
        assert result is not None
        assert isinstance(result, env_module.EnvManager)

        # Second call returns same instance
        result2 = get_env()
        assert result2 is result

    def test_load_env_with_project_root(self, tmp_path):
        """Lines 352-353: load_env with project_root sets the path."""
        from sagaz.core import env as env_module

        env_module._global_env = None  # Reset

        from sagaz.core.env import load_env

        # Pass project_root – covers line that sets env.project_root
        # The .env file doesn't exist, so load returns False
        result = load_env(project_root=str(tmp_path))
        # Returns bool (True/False depending on whether .env exists)
        assert isinstance(result, bool)

    def test_load_env_no_project_root(self):
        """Line 353: load_env without project_root calls env.load()."""
        from sagaz.core import env as env_module

        env_module._global_env = None  # Reset

        from sagaz.core.env import load_env

        result = load_env()  # No project_root - covers the else path
        assert isinstance(result, bool)


class TestEnvDotenvFallback:
    """Lines 18-19: load_dotenv = None when dotenv not installed."""

    def test_env_module_works_without_dotenv(self):
        """Simulate dotenv not available by inspecting fallback behavior."""
        import importlib

        # Save current state
        original_dotenv = sys.modules.get("dotenv")
        original_dotenv_main = sys.modules.get("dotenv.main")
        original_module = sys.modules.get("sagaz.core.env")

        # Remove dotenv from sys.modules to simulate it being unavailable
        for key in list(sys.modules.keys()):
            if key.startswith("dotenv"):
                sys.modules.pop(key)

        # Remove our module for re-import
        sys.modules.pop("sagaz.core.env", None)

        # Prevent dotenv from being importable
        sys.modules["dotenv"] = None  # Blocks import

        try:
            import sagaz.core.env as env_mod

            importlib.reload(env_mod)
            # load_dotenv should be None because of the except ImportError block
            assert env_mod.load_dotenv is None

            # EnvManager.load should handle this gracefully
            env_instance = env_mod.EnvManager(auto_load=False)
            result = env_instance.load()  # Should return False (no dotenv)
            assert result is False
        finally:
            # Restore sys.modules
            del sys.modules["dotenv"]
            if original_dotenv is not None:
                sys.modules["dotenv"] = original_dotenv
            if original_dotenv_main is not None:
                sys.modules["dotenv.main"] = original_dotenv_main
            # Restore original module
            sys.modules.pop("sagaz.core.env", None)
            if original_module is not None:
                sys.modules["sagaz.core.env"] = original_module
            # Reload to get the real version back
            importlib.reload(sys.modules["sagaz.core.env"])


# =============================================================================
# env.py - additional missing lines: 71-73, 90-96, 100-105, 109-112,
#           145, 148-149, 186, 201-322
# =============================================================================


class TestEnvManagerGetMethods:
    """Cover get(), get_bool(), get_int() methods."""

    def test_get_returns_value(self):
        """Line 90+: get() returns the env var value."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        os.environ["TEST_GET_KEY"] = "hello"
        try:
            assert env.get("TEST_GET_KEY") == "hello"
        finally:
            del os.environ["TEST_GET_KEY"]

    def test_get_missing_required_raises(self):
        """Lines 92-94: get() raises ValueError when required and missing."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        os.environ.pop("TEST_MISSING_REQ", None)
        with pytest.raises(ValueError, match="Required environment variable not set"):
            env.get("TEST_MISSING_REQ", required=True)

    def test_get_missing_optional_returns_default(self):
        """Line 96: get() returns default when key missing (not required)."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        os.environ.pop("TEST_OPT_KEY", None)
        result = env.get("TEST_OPT_KEY", default="fallback")
        assert result == "fallback"

    def test_get_bool_true_values(self):
        """Lines 100-102: get_bool() recognises truthy strings."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        for val in ("true", "1", "yes", "on"):
            os.environ["TEST_BOOL_KEY"] = val
            assert env.get_bool("TEST_BOOL_KEY") is True
        del os.environ["TEST_BOOL_KEY"]

    def test_get_bool_false_values(self):
        """Lines 103-104: get_bool() recognises falsy strings."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        for val in ("false", "0", "no", "off"):
            os.environ["TEST_BOOL_KEY"] = val
            assert env.get_bool("TEST_BOOL_KEY") is False
        del os.environ["TEST_BOOL_KEY"]

    def test_get_bool_default_on_unknown(self):
        """Line 105: get_bool() returns default for unrecognised strings."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        os.environ["TEST_BOOL_KEY"] = "maybe"
        result = env.get_bool("TEST_BOOL_KEY", default=True)
        assert result is True
        del os.environ["TEST_BOOL_KEY"]

    def test_get_int_valid(self):
        """Line 110: get_int() parses an integer."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        os.environ["TEST_INT_KEY"] = "42"
        assert env.get_int("TEST_INT_KEY") == 42
        del os.environ["TEST_INT_KEY"]

    def test_get_int_invalid_returns_default(self):
        """Lines 111-112: get_int() returns default on parse failure."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        os.environ["TEST_INT_KEY"] = "not_a_number"
        result = env.get_int("TEST_INT_KEY", default=99)
        assert result == 99
        del os.environ["TEST_INT_KEY"]


class TestEnvSubstituteExtra:
    """Cover substitute() and substitute_dict() missing branches."""

    def test_substitute_default_with_existing_value(self):
        """Line 145: ${VAR:-default} returns actual value when var is set."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        os.environ["EXISTS_VAR"] = "actual"
        try:
            result = env.substitute("${EXISTS_VAR:-fallback}")
            assert result == "actual"
        finally:
            del os.environ["EXISTS_VAR"]

    def test_substitute_required_missing_with_custom_message(self):
        """Lines 148-149: ${VAR:?custom_error} raises with custom message."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        os.environ.pop("MISSING_REQUIRED_VAR", None)
        with pytest.raises(ValueError, match="please set the variable"):
            env.substitute("${MISSING_REQUIRED_VAR:?please set the variable}")

    def test_substitute_dict_non_string_non_list_value(self):
        """Line 186: substitute_dict keeps non-string, non-list values as-is."""
        import os
        from sagaz.core.env import EnvManager

        env = EnvManager(auto_load=False)
        data = {
            "count": 42,          # int - kept as-is
            "enabled": True,      # bool - kept as-is
            "ratio": 0.75,        # float - kept as-is
        }
        result = env.substitute_dict(data)
        assert result["count"] == 42
        assert result["enabled"] is True
        assert result["ratio"] == 0.75


class TestEnvLoadDotenv:
    """Line 71-73: load_dotenv call when file is found."""

    def test_load_with_real_dotenv_file(self, tmp_path):
        """Lines 71-73: load() calls load_dotenv when file exists."""
        from sagaz.core.env import EnvManager

        env_file = tmp_path / ".env"
        env_file.write_text("TEST_DOTENV_KEY=loaded_value\n")

        env = EnvManager(project_root=str(tmp_path), auto_load=False)
        result = env.load()
        assert result is True
        assert env._loaded is True

    def test_load_idempotent_when_already_loaded(self, tmp_path):
        """Line 68: load() returns True without re-loading when _loaded=True."""
        from sagaz.core.env import EnvManager

        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")

        env = EnvManager(project_root=str(tmp_path), auto_load=False)
        env.load()
        # Second load should be idempotent/skipped
        result = env.load()
        assert result is True


class TestEnvCreateTemplate:
    """Lines 201-322: create_env_template() method."""

    def test_create_env_template_minimal(self, tmp_path):
        """Lines 201-322: generates .env template file."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(target, config_data={})

        assert target.exists()
        content = target.read_text()
        assert "SAGAZ_ENV=development" in content

    def test_create_env_template_with_postgresql_storage(self, tmp_path):
        """Lines 215-236: postgresql storage config section."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(
            target,
            config_data={
                "storage": {"type": "postgresql"},
            },
        )
        content = target.read_text()
        assert "SAGAZ_STORAGE" in content

    def test_create_env_template_with_redis_storage(self, tmp_path):
        """Lines 237-242: redis storage config section."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(
            target,
            config_data={"storage": {"type": "redis"}},
        )
        content = target.read_text()
        assert "redis://" in content

    def test_create_env_template_with_kafka_broker(self, tmp_path):
        """Lines 248-262: kafka broker config section."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(
            target,
            config_data={"broker": {"type": "kafka"}},
        )
        content = target.read_text()
        assert "SAGAZ_BROKER" in content

    def test_create_env_template_with_rabbitmq_broker(self, tmp_path):
        """Lines 263-273: rabbitmq broker config section."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(
            target,
            config_data={"broker": {"type": "rabbitmq"}},
        )
        content = target.read_text()
        assert "SAGAZ_BROKER" in content

    def test_create_env_template_with_redis_broker(self, tmp_path):
        """Lines 274-279: redis broker config section."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(
            target,
            config_data={"broker": {"type": "redis"}},
        )
        content = target.read_text()
        assert "redis://" in content

    def test_create_env_template_with_prometheus(self, tmp_path):
        """Lines 285-292: prometheus observability config section."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(
            target,
            config_data={
                "observability": {"prometheus": {"enabled": True}},
            },
        )
        content = target.read_text()
        assert "SAGAZ_METRICS_ENABLED" in content

    def test_create_env_template_with_tracing(self, tmp_path):
        """Lines 294-300: tracing config section."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(
            target,
            config_data={
                "observability": {"tracing": {"enabled": True}},
            },
        )
        content = target.read_text()
        assert "SAGAZ_TRACING_ENABLED" in content

    def test_create_env_template_outbox_section(self, tmp_path):
        """Lines 311-319: outbox config section."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(
            target,
            config_data={},
            include_examples=True,
        )
        content = target.read_text()
        assert "Outbox" in content

    def test_create_env_template_unknown_storage_type(self, tmp_path):
        """Line 237->244: elif storage=redis is False when storage is 'sqlite'."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(
            target,
            config_data={"storage": {"type": "sqlite"}},
        )
        content = target.read_text()
        assert "SAGAZ_STORAGE_TYPE=sqlite" in content

    def test_create_env_template_unknown_broker_type(self, tmp_path):
        """Line 274->281: elif broker=redis is False when broker is 'pulsar'."""
        from sagaz.core.env import EnvManager

        target = tmp_path / ".env.template"
        EnvManager.create_env_template(
            target,
            config_data={"broker": {"type": "pulsar"}},
        )
        content = target.read_text()
        assert "SAGAZ_BROKER_TYPE=pulsar" in content

