"""Test environment variable management and configuration."""

import os
import tempfile
from pathlib import Path

import pytest

from sagaz.core.config import SagaConfig
from sagaz.core.env import EnvManager


class TestEnvManager:
    """Test EnvManager functionality."""

    def test_get_with_default(self):
        """Test getting environment variable with default."""
        env = EnvManager(auto_load=False)

        # Non-existent variable
        assert env.get("NONEXISTENT_VAR", "default") == "default"

        # Existing variable
        os.environ["TEST_VAR"] = "test_value"
        assert env.get("TEST_VAR") == "test_value"
        del os.environ["TEST_VAR"]

    def test_get_bool(self):
        """Test boolean parsing."""
        env = EnvManager(auto_load=False)

        test_cases = [
            ("true", True),
            ("True", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("False", False),
            ("0", False),
            ("no", False),
            ("", False),  # Default
        ]

        for value, expected in test_cases:
            os.environ["TEST_BOOL"] = value
            assert env.get_bool("TEST_BOOL") == expected

        del os.environ["TEST_BOOL"]

    def test_get_int(self):
        """Test integer parsing."""
        env = EnvManager(auto_load=False)

        os.environ["TEST_INT"] = "42"
        assert env.get_int("TEST_INT") == 42

        os.environ["TEST_INT"] = "invalid"
        assert env.get_int("TEST_INT", default=10) == 10

        del os.environ["TEST_INT"]

    def test_substitute_simple(self):
        """Test simple variable substitution."""
        env = EnvManager(auto_load=False)

        os.environ["DB_HOST"] = "localhost"
        os.environ["DB_PORT"] = "5432"

        result = env.substitute("postgresql://${DB_HOST}:${DB_PORT}/db")
        assert result == "postgresql://localhost:5432/db"

        del os.environ["DB_HOST"]
        del os.environ["DB_PORT"]

    def test_substitute_with_default(self):
        """Test substitution with default values."""
        env = EnvManager(auto_load=False)

        # Variable not set - use default
        result = env.substitute("${MISSING_VAR:-default_value}")
        assert result == "default_value"

        # Variable set - use actual value
        os.environ["PRESENT_VAR"] = "actual_value"
        result = env.substitute("${PRESENT_VAR:-default_value}")
        assert result == "actual_value"
        del os.environ["PRESENT_VAR"]

    def test_substitute_required(self):
        """Test substitution with required variables."""
        env = EnvManager(auto_load=False)

        # Missing required variable should raise error
        with pytest.raises(ValueError, match="This is required"):
            env.substitute("${REQUIRED_VAR:?This is required}")

        # Present required variable should work
        os.environ["REQUIRED_VAR"] = "value"
        result = env.substitute("${REQUIRED_VAR:?This is required}")
        assert result == "value"
        del os.environ["REQUIRED_VAR"]

    def test_substitute_dict(self):
        """Test recursive dictionary substitution."""
        env = EnvManager(auto_load=False)

        os.environ["DB_HOST"] = "dbhost"
        os.environ["DB_PORT"] = "5432"

        data = {
            "storage": {
                "host": "${DB_HOST}",
                "port": "${DB_PORT}",
                "nested": {"url": "postgresql://${DB_HOST}:${DB_PORT}/db"},
            },
            "list": ["${DB_HOST}", "${DB_PORT}"],
        }

        result = env.substitute_dict(data)

        assert result["storage"]["host"] == "dbhost"
        assert result["storage"]["port"] == "5432"
        assert result["storage"]["nested"]["url"] == "postgresql://dbhost:5432/db"
        assert result["list"] == ["dbhost", "5432"]

        del os.environ["DB_HOST"]
        del os.environ["DB_PORT"]

    def test_load_dotenv_file(self):
        """Test loading .env file."""
        if EnvManager is None:
            pytest.skip("python-dotenv not installed")

        # Create temporary .env file
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "TEST_VAR_1=value1\nTEST_VAR_2=value2\n# Comment line\nTEST_VAR_3=value3"
            )

            env = EnvManager(project_root=tmpdir, auto_load=True)

            assert os.environ.get("TEST_VAR_1") == "value1"
            assert os.environ.get("TEST_VAR_2") == "value2"
            assert os.environ.get("TEST_VAR_3") == "value3"

            # Cleanup
            del os.environ["TEST_VAR_1"]
            del os.environ["TEST_VAR_2"]
            del os.environ["TEST_VAR_3"]


class TestSagaConfigWithEnv:
    """Test SagaConfig with environment variables."""

    def test_from_env_with_urls(self):
        """Test loading config from environment variables with URLs."""
        os.environ["SAGAZ_STORAGE_URL"] = "postgresql://localhost/testdb"
        os.environ["SAGAZ_BROKER_URL"] = "kafka://localhost:9092"
        os.environ["SAGAZ_METRICS"] = "true"
        os.environ["SAGAZ_TRACING"] = "false"

        config = SagaConfig.from_env(load_dotenv=False)

        assert config.storage is not None
        assert config.broker is not None
        assert config.metrics is True
        assert config.tracing is False

        # Cleanup
        del os.environ["SAGAZ_STORAGE_URL"]
        del os.environ["SAGAZ_BROKER_URL"]
        del os.environ["SAGAZ_METRICS"]
        del os.environ["SAGAZ_TRACING"]

    def test_from_env_with_components(self):
        """Test loading config from environment variable components."""
        os.environ["SAGAZ_STORAGE_TYPE"] = "postgresql"
        os.environ["SAGAZ_STORAGE_HOST"] = "dbhost"
        os.environ["SAGAZ_STORAGE_PORT"] = "5433"
        os.environ["SAGAZ_STORAGE_DB"] = "mydb"
        os.environ["SAGAZ_STORAGE_USER"] = "myuser"
        os.environ["SAGAZ_STORAGE_PASSWORD"] = "mypass"

        os.environ["SAGAZ_BROKER_TYPE"] = "redis"
        os.environ["SAGAZ_BROKER_URL"] = "redis://localhost:6379/1"

        config = SagaConfig.from_env(load_dotenv=False)

        assert config.storage is not None
        assert config.broker is not None

        # Cleanup
        for key in list(os.environ.keys()):
            if key.startswith("SAGAZ_"):
                del os.environ[key]

    def test_from_file_with_substitution(self):
        """Test loading config from YAML with env var substitution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set environment variables
            os.environ["TEST_DB_HOST"] = "testhost"
            os.environ["TEST_DB_PORT"] = "5432"
            os.environ["TEST_BROKER_TYPE"] = "redis"

            # Create config file
            config_file = Path(tmpdir) / "sagaz.yaml"
            config_file.write_text("""
version: "1.0"

storage:
  type: postgresql
  connection:
    host: ${TEST_DB_HOST}
    port: ${TEST_DB_PORT:-5432}
    database: ${TEST_DB_NAME:-sagaz}
    user: postgres
    password: postgres

broker:
  type: ${TEST_BROKER_TYPE}
  connection:
    host: localhost
    port: 6379

observability:
  prometheus:
    enabled: true
  tracing:
    enabled: false
""")

            config = SagaConfig.from_file(config_file)

            assert config.storage is not None
            assert config.broker is not None

            # Cleanup
            del os.environ["TEST_DB_HOST"]
            del os.environ["TEST_DB_PORT"]
            del os.environ["TEST_BROKER_TYPE"]


class TestEnvTemplateGeneration:
    """Test .env template generation."""

    def test_create_env_template(self):
        """Test creating .env.template file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / ".env.template"

            config_data = {
                "storage": {"type": "postgresql"},
                "broker": {"type": "kafka"},
                "observability": {"prometheus": {"enabled": True}, "tracing": {"enabled": True}},
            }

            EnvManager.create_env_template(template_path, config_data)

            assert template_path.exists()
            content = template_path.read_text()

            # Check for key sections
            assert "SAGAZ_STORAGE_TYPE" in content
            assert "SAGAZ_BROKER_TYPE" in content
            assert "SAGAZ_METRICS_ENABLED" in content
            assert "SAGAZ_TRACING_ENABLED" in content
            assert "postgresql" in content
            assert "kafka" in content
            assert "DO NOT commit" in content  # Security warning

    def test_env_manager_load_without_dotenv(self):
        """Test load when python-dotenv is not available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("TEST=value")

            env = EnvManager(project_root=tmpdir, auto_load=False)

            # Mock load_dotenv as None
            import sagaz.core.env as env_module

            original_load_dotenv = env_module.load_dotenv
            env_module.load_dotenv = None

            try:
                result = env.load(env_file)
                assert result is False  # Should return False when dotenv not available
            finally:
                env_module.load_dotenv = original_load_dotenv

    def test_env_manager_load_nonexistent_file(self):
        """Test load with non-existent .env file."""
        env = EnvManager(auto_load=False)
        result = env.load(env_file="/nonexistent/path/.env")
        assert result is False

    def test_env_manager_get_required_missing(self):
        """Test get with required=True and missing variable."""
        env = EnvManager(auto_load=False)

        with pytest.raises(ValueError, match="Required environment variable"):
            env.get("MISSING_REQUIRED_VAR", required=True)

    def test_env_manager_get_bool_edge_cases(self):
        """Test boolean parsing edge cases."""
        env = EnvManager(auto_load=False)

        # Test 'on' and 'off'
        os.environ["TEST_BOOL"] = "on"
        assert env.get_bool("TEST_BOOL") is True

        os.environ["TEST_BOOL"] = "off"
        assert env.get_bool("TEST_BOOL") is False

        # Test case insensitivity
        os.environ["TEST_BOOL"] = "YES"
        assert env.get_bool("TEST_BOOL") is True

        os.environ["TEST_BOOL"] = "NO"
        assert env.get_bool("TEST_BOOL") is False

        del os.environ["TEST_BOOL"]

    def test_env_manager_load_with_override(self):
        """Test load with override=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("OVERRIDE_TEST=new_value")

            # Set existing value
            os.environ["OVERRIDE_TEST"] = "old_value"

            env = EnvManager(project_root=tmpdir, auto_load=False)
            env.load(env_file, override=True)

            # Should be overridden
            assert os.environ.get("OVERRIDE_TEST") == "new_value"

            # Cleanup
            if "OVERRIDE_TEST" in os.environ:
                del os.environ["OVERRIDE_TEST"]
