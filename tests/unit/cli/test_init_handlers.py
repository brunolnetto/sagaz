"""
Tests for sagaz/cli/_init_handlers.py

Covers deployment initialisation helpers:
  _init_local, _log_local_init_start, _init_docker_compose,
  _copy_docker_compose_files, _get_broker_config,
  _create_inmemory_docker_compose, _init_monitoring,
  _log_local_init_complete, _init_selfhost, _create_systemd_service,
  _create_selfhost_monitoring, _init_k8s, _log_k8s_init_start,
  _prepare_k8s_directory, _copy_k8s_manifests, _copy_k8s_observability,
  _copy_k8s_benchmarks, _log_k8s_init_complete, _create_k8s_benchmark_config,
  _init_hybrid, _init_benchmarks,
  _copy_example_saga, _copy_dir_resource, _copy_resource
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop(*args, **kwargs):
    pass


# ---------------------------------------------------------------------------
# _get_broker_config
# ---------------------------------------------------------------------------


class TestGetBrokerConfig:
    def test_redis(self):
        from sagaz.cli._init_handlers import _get_broker_config

        image, port, env = _get_broker_config("redis")
        assert image == "redis:7-alpine"
        assert port == 6379

    def test_rabbitmq(self):
        from sagaz.cli._init_handlers import _get_broker_config

        image, port, env = _get_broker_config("rabbitmq")
        assert "rabbitmq" in image
        assert port == 5672

    def test_kafka(self):
        from sagaz.cli._init_handlers import _get_broker_config

        image, port, env = _get_broker_config("kafka")
        assert "kafka" in image.lower()
        assert port == 9092

    def test_unknown_broker_falls_back_to_redis(self):
        from sagaz.cli._init_handlers import _get_broker_config

        image, port, env = _get_broker_config("unknown")
        assert port == 6379  # falls back to redis defaults


# ---------------------------------------------------------------------------
# _create_inmemory_docker_compose
# ---------------------------------------------------------------------------


class TestCreateInmemoryDockerCompose:
    def test_creates_file(self, tmp_path):
        from sagaz.cli._init_handlers import _create_inmemory_docker_compose

        with patch("sagaz.cli._init_handlers.click") as mock_click:
            old_cwd = Path.cwd()
            import os

            os.chdir(tmp_path)
            try:
                _create_inmemory_docker_compose("redis")
                assert (tmp_path / "docker-compose.yaml").exists()
                content = (tmp_path / "docker-compose.yaml").read_text()
                assert "redis" in content
            finally:
                os.chdir(old_cwd)

    def test_creates_file_kafka(self, tmp_path):
        from sagaz.cli._init_handlers import _create_inmemory_docker_compose

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.click"):
                _create_inmemory_docker_compose("kafka")
            content = (tmp_path / "docker-compose.yaml").read_text()
            assert "kafka" in content.lower()
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _copy_docker_compose_files
# ---------------------------------------------------------------------------


class TestCopyDockerComposeFiles:
    def test_dev_mode(self, tmp_path):
        from sagaz.cli._init_handlers import _copy_docker_compose_files

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers._create_inmemory_docker_compose") as m:
                _copy_docker_compose_files("redis", False, dev_mode=True)
                m.assert_called_once_with("redis")
        finally:
            os.chdir(old_cwd)

    def test_with_ha(self):
        from sagaz.cli._init_handlers import _copy_docker_compose_files

        with patch("sagaz.cli._init_handlers._copy_resource") as mock_res, patch(
            "sagaz.cli._init_handlers._copy_dir_resource"
        ) as mock_dir:
            _copy_docker_compose_files("redis", True, dev_mode=False)
            mock_res.assert_any_call("local/postgres-ha/docker-compose.yaml", "docker-compose.yaml")

    def test_no_ha_no_dev(self):
        from sagaz.cli._init_handlers import _copy_docker_compose_files

        with patch("sagaz.cli._init_handlers._copy_resource") as mock_res:
            _copy_docker_compose_files("redis", False, dev_mode=False)
            mock_res.assert_called_once_with("local/redis/docker-compose.yaml", "docker-compose.yaml")


# ---------------------------------------------------------------------------
# _init_docker_compose
# ---------------------------------------------------------------------------


class TestInitDockerCompose:
    def test_skips_if_exists_and_no_confirm(self, tmp_path):
        from sagaz.cli._init_handlers import _init_docker_compose

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "docker-compose.yaml").write_text("existing")
            with patch("sagaz.cli._init_handlers.click") as mock_click:
                mock_click.confirm.return_value = False
                mock_click.echo = _noop
                _init_docker_compose("redis", False)
            # File should remain unchanged
            assert (tmp_path / "docker-compose.yaml").read_text() == "existing"
        finally:
            os.chdir(old_cwd)

    def test_copies_when_no_existing_file(self, tmp_path):
        from sagaz.cli._init_handlers import _init_docker_compose

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers._copy_docker_compose_files") as mock_copy:
                _init_docker_compose("redis", False)
                mock_copy.assert_called_once()
        finally:
            os.chdir(old_cwd)

    def test_overwrites_on_confirm(self, tmp_path):
        from sagaz.cli._init_handlers import _init_docker_compose

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "docker-compose.yaml").write_text("old")
            with patch("sagaz.cli._init_handlers.click") as mock_click, patch(
                "sagaz.cli._init_handlers._copy_docker_compose_files"
            ) as mock_copy:
                mock_click.confirm.return_value = True
                mock_click.echo = _noop
                _init_docker_compose("redis", False)
                mock_copy.assert_called_once()
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _init_monitoring
# ---------------------------------------------------------------------------


class TestInitMonitoring:
    def test_with_ha(self):
        from sagaz.cli._init_handlers import _init_monitoring

        with patch("sagaz.cli._init_handlers._copy_dir_resource") as mock_dir:
            _init_monitoring("redis", True)
            mock_dir.assert_called_once_with("local/postgres-ha/monitoring", "monitoring")

    def test_without_ha(self):
        from sagaz.cli._init_handlers import _init_monitoring

        with patch("sagaz.cli._init_handlers._copy_dir_resource") as mock_dir:
            _init_monitoring("redis", False)
            mock_dir.assert_called_once_with("local/redis/monitoring", "monitoring")


# ---------------------------------------------------------------------------
# _log_local_init_start
# ---------------------------------------------------------------------------


class TestLogLocalInitStart:
    def test_dev_mode_log(self):
        from sagaz.cli._init_handlers import _log_local_init_start

        mock_console = MagicMock()
        with patch("sagaz.cli._init_handlers.console", mock_console):
            _log_local_init_start("redis", False, "postgresql", dev_mode=True)
            mock_console.print.assert_called_once()
            msg = mock_console.print.call_args[0][0]
            assert "development" in msg.lower() or "in-memory" in msg.lower()

    def test_ha_log(self):
        from sagaz.cli._init_handlers import _log_local_init_start

        mock_console = MagicMock()
        with patch("sagaz.cli._init_handlers.console", mock_console):
            _log_local_init_start("redis", True, "postgresql", dev_mode=False)
            mock_console.print.assert_called_once()
            msg = mock_console.print.call_args[0][0]
            assert "HA" in msg or "primary" in msg.lower() or "replica" in msg.lower()

    def test_normal_log(self):
        from sagaz.cli._init_handlers import _log_local_init_start

        mock_console = MagicMock()
        with patch("sagaz.cli._init_handlers.console", mock_console):
            _log_local_init_start("redis", False, "postgresql", dev_mode=False)
            mock_console.print.assert_called_once()

    def test_no_console(self):
        from sagaz.cli._init_handlers import _log_local_init_start

        with patch("sagaz.cli._init_handlers.console", None):
            # Should not raise
            _log_local_init_start("redis", False, "postgresql", dev_mode=False)


# ---------------------------------------------------------------------------
# _log_local_init_complete
# ---------------------------------------------------------------------------


class TestLogLocalInitComplete:
    def test_no_console(self):
        from sagaz.cli._init_handlers import _log_local_init_complete

        with patch("sagaz.cli._init_handlers.console", None):
            _log_local_init_complete(True, True, True)  # must not raise

    def test_dev_mode(self):
        from sagaz.cli._init_handlers import _log_local_init_complete

        mock_console = MagicMock()
        with patch("sagaz.cli._init_handlers.console", mock_console):
            _log_local_init_complete(False, False, dev_mode=True)
            assert mock_console.print.called

    def test_with_observability(self):
        from sagaz.cli._init_handlers import _log_local_init_complete

        mock_console = MagicMock()
        with patch("sagaz.cli._init_handlers.console", mock_console):
            _log_local_init_complete(with_observability=True, with_ha=False, dev_mode=False)
            calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("3000" in c for c in calls)

    def test_with_ha(self):
        from sagaz.cli._init_handlers import _log_local_init_complete

        mock_console = MagicMock()
        with patch("sagaz.cli._init_handlers.console", mock_console):
            _log_local_init_complete(with_observability=False, with_ha=True, dev_mode=False)
            calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("5432" in c or "Primary" in c or "primary" in c for c in calls)


# ---------------------------------------------------------------------------
# _init_local
# ---------------------------------------------------------------------------


class TestInitLocal:
    def test_calls_all_steps(self, tmp_path):
        from sagaz.cli._init_handlers import _init_local

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers._log_local_init_start") as m_start, patch(
                "sagaz.cli._init_handlers._init_docker_compose"
            ) as m_compose, patch(
                "sagaz.cli._init_handlers._init_monitoring"
            ) as m_mon, patch(
                "sagaz.cli._init_handlers._log_local_init_complete"
            ) as m_complete:
                _init_local("redis", with_observability=True)
                m_start.assert_called_once()
                m_compose.assert_called_once()
                m_mon.assert_called_once()
                m_complete.assert_called_once()
        finally:
            os.chdir(old_cwd)

    def test_no_monitoring_when_disabled(self, tmp_path):
        from sagaz.cli._init_handlers import _init_local

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers._log_local_init_start"), patch(
                "sagaz.cli._init_handlers._init_docker_compose"
            ), patch("sagaz.cli._init_handlers._init_monitoring") as m_mon, patch(
                "sagaz.cli._init_handlers._log_local_init_complete"
            ):
                _init_local("redis", with_observability=False)
                m_mon.assert_not_called()
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _create_systemd_service
# ---------------------------------------------------------------------------


class TestCreateSystemdService:
    def test_creates_service_file(self, tmp_path):
        from sagaz.cli._init_handlers import _create_systemd_service

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "selfhost").mkdir()
            with patch("sagaz.cli._init_handlers.click"):
                _create_systemd_service("sagaz-worker", "Test Service", "python -m sagaz.worker")
            assert (tmp_path / "selfhost" / "sagaz-worker.service").exists()
            content = (tmp_path / "selfhost" / "sagaz-worker.service").read_text()
            assert "Test Service" in content
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _create_selfhost_monitoring
# ---------------------------------------------------------------------------


class TestCreateSelfhostMonitoring:
    def test_creates_prometheus_config(self, tmp_path):
        from sagaz.cli._init_handlers import _create_selfhost_monitoring

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "selfhost").mkdir()
            with patch("sagaz.cli._init_handlers.click"):
                _create_selfhost_monitoring()
            assert (tmp_path / "selfhost" / "prometheus.yml").exists()
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _init_selfhost
# ---------------------------------------------------------------------------


class TestInitSelfhost:
    def test_basic(self, tmp_path):
        from sagaz.cli._init_handlers import _init_selfhost

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            mock_console = MagicMock()
            with patch("sagaz.cli._init_handlers.console", mock_console), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_selfhost("redis", with_observability=False)
            assert (tmp_path / "selfhost").is_dir()
            assert (tmp_path / "selfhost" / "sagaz.env").exists()
            assert (tmp_path / "selfhost" / "install.sh").exists()
        finally:
            os.chdir(old_cwd)

    def test_with_observability(self, tmp_path):
        from sagaz.cli._init_handlers import _init_selfhost

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.console", MagicMock()), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_selfhost("redis", with_observability=True)
            assert (tmp_path / "selfhost" / "prometheus.yml").exists()
        finally:
            os.chdir(old_cwd)

    def test_kafka_broker_env(self, tmp_path):
        from sagaz.cli._init_handlers import _init_selfhost

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.console", MagicMock()), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_selfhost("kafka", with_observability=False)
            env = (tmp_path / "selfhost" / "sagaz.env").read_text()
            assert "KAFKA" in env
        finally:
            os.chdir(old_cwd)

    def test_rabbitmq_broker_env(self, tmp_path):
        from sagaz.cli._init_handlers import _init_selfhost

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.console", MagicMock()), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_selfhost("rabbitmq", with_observability=False)
            env = (tmp_path / "selfhost" / "sagaz.env").read_text()
            assert "RABBITMQ" in env
        finally:
            os.chdir(old_cwd)

    def test_separate_outbox(self, tmp_path):
        from sagaz.cli._init_handlers import _init_selfhost

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.console", MagicMock()), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_selfhost("redis", with_observability=False, separate_outbox=True)
            env = (tmp_path / "selfhost" / "sagaz.env").read_text()
            assert "OUTBOX_URL" in env
        finally:
            os.chdir(old_cwd)

    def test_no_console(self, tmp_path):
        from sagaz.cli._init_handlers import _init_selfhost

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.console", None), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_selfhost("redis", with_observability=False)
            # Should still create files
            assert (tmp_path / "selfhost").is_dir()
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _log_k8s_init_start / _log_k8s_init_complete
# ---------------------------------------------------------------------------


class TestLogK8s:
    def test_log_start_with_ha(self):
        from sagaz.cli._init_handlers import _log_k8s_init_start

        mock_console = MagicMock()
        with patch("sagaz.cli._init_handlers.console", mock_console):
            _log_k8s_init_start(True, "postgresql")
            mock_console.print.assert_called_once()

    def test_log_start_without_ha(self):
        from sagaz.cli._init_handlers import _log_k8s_init_start

        mock_console = MagicMock()
        with patch("sagaz.cli._init_handlers.console", mock_console):
            _log_k8s_init_start(False, "postgresql")
            mock_console.print.assert_called_once()

    def test_log_start_no_console(self):
        from sagaz.cli._init_handlers import _log_k8s_init_start

        with patch("sagaz.cli._init_handlers.console", None):
            _log_k8s_init_start(False, "postgresql")  # must not raise

    def test_log_complete_with_ha(self):
        from sagaz.cli._init_handlers import _log_k8s_init_complete

        mock_console = MagicMock()
        with patch("sagaz.cli._init_handlers.console", mock_console):
            _log_k8s_init_complete(True)
            calls = [str(c) for c in mock_console.print.call_args_list]
            assert any("5432" in c or "HA" in c or "primary" in c.lower() for c in calls)

    def test_log_complete_without_ha(self):
        from sagaz.cli._init_handlers import _log_k8s_init_complete

        mock_console = MagicMock()
        with patch("sagaz.cli._init_handlers.console", mock_console):
            _log_k8s_init_complete(False)
            mock_console.print.assert_called_once()

    def test_log_complete_no_console(self):
        from sagaz.cli._init_handlers import _log_k8s_init_complete

        with patch("sagaz.cli._init_handlers.console", None):
            _log_k8s_init_complete(False)  # must not raise


# ---------------------------------------------------------------------------
# _prepare_k8s_directory
# ---------------------------------------------------------------------------


class TestPrepareK8sDirectory:
    def test_creates_new_dir(self, tmp_path):
        from sagaz.cli._init_handlers import _prepare_k8s_directory

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            result = _prepare_k8s_directory()
            assert result is True
            assert (tmp_path / "k8s").is_dir()
        finally:
            os.chdir(old_cwd)

    def test_aborts_on_reject(self, tmp_path):
        from sagaz.cli._init_handlers import _prepare_k8s_directory

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "k8s").mkdir()
            with patch("sagaz.cli._init_handlers.click") as mock_click:
                mock_click.confirm.return_value = False
                mock_click.echo = _noop
                result = _prepare_k8s_directory()
                assert result is False
        finally:
            os.chdir(old_cwd)

    def test_overwrites_on_confirm(self, tmp_path):
        from sagaz.cli._init_handlers import _prepare_k8s_directory

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "k8s").mkdir()
            (tmp_path / "k8s" / "old.yaml").write_text("old")
            with patch("sagaz.cli._init_handlers.click") as mock_click:
                mock_click.confirm.return_value = True
                mock_click.echo = _noop
                result = _prepare_k8s_directory()
                assert result is True
                # old file should be gone
                assert not (tmp_path / "k8s" / "old.yaml").exists()
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _copy_k8s_manifests
# ---------------------------------------------------------------------------


class TestCopyK8sManifests:
    def test_postgresql_no_ha(self):
        from sagaz.cli._init_handlers import _copy_k8s_manifests

        with patch("sagaz.cli._init_handlers._copy_resource") as mock_res, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = _noop
            _copy_k8s_manifests(False, False, "postgresql")
            mock_res.assert_any_call("k8s/postgresql.yaml", "k8s/postgresql.yaml")

    def test_postgresql_with_ha(self, tmp_path):
        from sagaz.cli._init_handlers import _copy_k8s_manifests

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "k8s").mkdir()
            with patch("sagaz.cli._init_handlers._copy_resource") as mock_res, patch(
                "sagaz.cli._init_handlers._copy_dir_resource"
            ), patch("sagaz.cli._init_handlers.click") as mock_click:
                mock_click.echo = _noop
                _copy_k8s_manifests(True, False, "postgresql")
                mock_res.assert_any_call("k8s/postgresql-ha.yaml", "k8s/postgresql-ha.yaml")
        finally:
            os.chdir(old_cwd)

    def test_in_memory_storage(self):
        from sagaz.cli._init_handlers import _copy_k8s_manifests

        with patch("sagaz.cli._init_handlers._copy_resource") as mock_res, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = _noop
            _copy_k8s_manifests(False, False, "in-memory")
            # Should not copy postgresql.yaml
            calls = [str(c) for c in mock_res.call_args_list]
            assert not any("postgresql.yaml" in c for c in calls)

    def test_separate_outbox(self):
        from sagaz.cli._init_handlers import _copy_k8s_manifests

        with patch("sagaz.cli._init_handlers._copy_resource") as mock_res, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = _noop
            _copy_k8s_manifests(False, True, "postgresql")
            mock_res.assert_any_call("k8s/outbox-postgresql.yaml", "k8s/outbox-postgresql.yaml")


# ---------------------------------------------------------------------------
# _copy_k8s_observability / _copy_k8s_benchmarks
# ---------------------------------------------------------------------------


class TestCopyK8sOptionals:
    def test_observability_enabled(self):
        from sagaz.cli._init_handlers import _copy_k8s_observability

        with patch("sagaz.cli._init_handlers._copy_resource") as mock_res, patch(
            "sagaz.cli._init_handlers._copy_dir_resource"
        ):
            _copy_k8s_observability(True)
            mock_res.assert_any_call(
                "k8s/prometheus-monitoring.yaml", "k8s/prometheus-monitoring.yaml"
            )

    def test_observability_disabled(self):
        from sagaz.cli._init_handlers import _copy_k8s_observability

        with patch("sagaz.cli._init_handlers._copy_resource") as mock_res, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = _noop
            _copy_k8s_observability(False)
            mock_res.assert_not_called()

    def test_benchmarks_enabled(self, tmp_path):
        from sagaz.cli._init_handlers import _copy_k8s_benchmarks

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "k8s").mkdir()
            with patch("sagaz.cli._init_handlers.click") as mock_click:
                mock_click.echo = _noop
                _copy_k8s_benchmarks(True)
            assert (tmp_path / "k8s" / "benchmark").is_dir()
        finally:
            os.chdir(old_cwd)

    def test_benchmarks_disabled(self):
        from sagaz.cli._init_handlers import _copy_k8s_benchmarks

        with patch("sagaz.cli._init_handlers.click") as mock_click:
            mock_click.echo = MagicMock()
            _copy_k8s_benchmarks(False)
            # Just echo skip message; no file creation
            mock_click.echo.assert_called()


# ---------------------------------------------------------------------------
# _create_k8s_benchmark_config
# ---------------------------------------------------------------------------


class TestCreateK8sBenchmarkConfig:
    def test_creates_yaml_files(self, tmp_path):
        from sagaz.cli._init_handlers import _create_k8s_benchmark_config

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            (tmp_path / "k8s").mkdir()
            with patch("sagaz.cli._init_handlers.click") as mock_click:
                mock_click.echo = _noop
                _create_k8s_benchmark_config()
            assert (tmp_path / "k8s" / "benchmark" / "job.yaml").exists()
            assert (tmp_path / "k8s" / "benchmark" / "stress-job.yaml").exists()
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _init_k8s
# ---------------------------------------------------------------------------


class TestInitK8s:
    def test_basic(self, tmp_path):
        from sagaz.cli._init_handlers import _init_k8s

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers._log_k8s_init_start"), patch(
                "sagaz.cli._init_handlers._prepare_k8s_directory", return_value=True
            ), patch("sagaz.cli._init_handlers._copy_k8s_manifests"), patch(
                "sagaz.cli._init_handlers._copy_k8s_observability"
            ), patch(
                "sagaz.cli._init_handlers._copy_k8s_benchmarks"
            ), patch(
                "sagaz.cli._init_handlers._log_k8s_init_complete"
            ) as m_complete:
                _init_k8s(with_observability=True, with_benchmarks=False)
                m_complete.assert_called_once()
        finally:
            os.chdir(old_cwd)

    def test_aborts_when_prepare_returns_false(self, tmp_path):
        from sagaz.cli._init_handlers import _init_k8s

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers._log_k8s_init_start"), patch(
                "sagaz.cli._init_handlers._prepare_k8s_directory", return_value=False
            ), patch("sagaz.cli._init_handlers._copy_k8s_manifests") as m_copy:
                _init_k8s(with_observability=True, with_benchmarks=False)
                m_copy.assert_not_called()
        finally:
            os.chdir(old_cwd)

    def test_handles_exception(self, tmp_path):
        from sagaz.cli._init_handlers import _init_k8s

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers._log_k8s_init_start"), patch(
                "sagaz.cli._init_handlers._prepare_k8s_directory", return_value=True
            ), patch(
                "sagaz.cli._init_handlers._copy_k8s_manifests",
                side_effect=RuntimeError("boom"),
            ), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_k8s(with_observability=False, with_benchmarks=False)
                # Should not raise; exception is swallowed and click.echo called
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _init_hybrid
# ---------------------------------------------------------------------------


class TestInitHybrid:
    def test_redis(self, tmp_path):
        from sagaz.cli._init_handlers import _init_hybrid

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.console", MagicMock()), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_hybrid("redis")
            assert (tmp_path / "hybrid" / "README.md").exists()
            assert (tmp_path / "hybrid" / "docker-compose.yaml").exists()
            assert (tmp_path / "hybrid" / "hybrid.env").exists()
        finally:
            os.chdir(old_cwd)

    def test_kafka_env(self, tmp_path):
        from sagaz.cli._init_handlers import _init_hybrid

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.console", MagicMock()), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_hybrid("kafka")
            env = (tmp_path / "hybrid" / "hybrid.env").read_text()
            assert "kafka" in env.lower()
        finally:
            os.chdir(old_cwd)

    def test_rabbitmq_env(self, tmp_path):
        from sagaz.cli._init_handlers import _init_hybrid

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.console", MagicMock()), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_hybrid("rabbitmq")
            env = (tmp_path / "hybrid" / "hybrid.env").read_text()
            assert "amqp" in env.lower() or "rabbitmq" in env.lower()
        finally:
            os.chdir(old_cwd)

    def test_no_console(self, tmp_path):
        from sagaz.cli._init_handlers import _init_hybrid

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.console", None), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_hybrid("redis")
            assert (tmp_path / "hybrid").is_dir()
        finally:
            os.chdir(old_cwd)

    def test_in_memory_storage_skips_compose(self, tmp_path):
        from sagaz.cli._init_handlers import _init_hybrid

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.console", MagicMock()), patch(
                "sagaz.cli._init_handlers.click"
            ) as mock_click:
                mock_click.echo = _noop
                _init_hybrid("redis", oltp_storage="in-memory")
            # README and env should exist; compose not written for non-postgresql storage
            assert (tmp_path / "hybrid" / "README.md").exists()
            assert (tmp_path / "hybrid" / "hybrid.env").exists()
            assert not (tmp_path / "hybrid" / "docker-compose.yaml").exists()
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _init_benchmarks
# ---------------------------------------------------------------------------


class TestInitBenchmarks:
    def test_creates_run_script(self, tmp_path):
        from sagaz.cli._init_handlers import _init_benchmarks

        import os

        old_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            with patch("sagaz.cli._init_handlers.click") as mock_click:
                mock_click.echo = _noop
                _init_benchmarks()
            run_sh = tmp_path / "benchmarks" / "run.sh"
            assert run_sh.exists()
            content = run_sh.read_text()
            assert "profile" in content.lower() or "pytest" in content
        finally:
            os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# _copy_example_saga
# ---------------------------------------------------------------------------


class TestCopyExampleSaga:
    def test_simple_template(self, tmp_path):
        from sagaz.cli._init_handlers import _copy_example_saga

        with patch("sagaz.cli._init_handlers.click") as mock_click:
            mock_click.echo = _noop
            _copy_example_saga("simple", tmp_path)
        assert (tmp_path / "example_saga.py").exists()
        content = (tmp_path / "example_saga.py").read_text()
        assert "ExampleSaga" in content

    def test_package_example_success(self, tmp_path):
        from sagaz.cli._init_handlers import _copy_example_saga

        mock_traversable = MagicMock()
        mock_main = MagicMock()
        mock_main.read_text.return_value = "# test saga content"
        mock_traversable.joinpath.return_value = mock_main
        mock_files = MagicMock(return_value=mock_traversable)

        with patch("sagaz.cli._init_handlers.pkg_resources") as mock_pkg, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = _noop
            mock_source = MagicMock()
            mock_source.joinpath.return_value.read_text.return_value = "# saga"
            mock_pkg.files.return_value.joinpath.return_value = mock_source
            _copy_example_saga("order/processing", tmp_path)

    def test_package_example_fallback_on_error(self, tmp_path):
        from sagaz.cli._init_handlers import _copy_example_saga

        with patch("sagaz.cli._init_handlers.pkg_resources") as mock_pkg, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = MagicMock()
            # Make the inner try fail
            mock_pkg.files.side_effect = Exception("pkg error")
            _copy_example_saga("some/template", tmp_path)
            # Should emit ERROR message
            mock_click.echo.assert_called()

    def test_inner_read_fails_creates_simple(self, tmp_path):
        from sagaz.cli._init_handlers import _copy_example_saga

        with patch("sagaz.cli._init_handlers.pkg_resources") as mock_pkg, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = _noop
            # Make main.py read_text fail → should recursively call simple
            mock_source = MagicMock()
            mock_source.joinpath.return_value.read_text.side_effect = FileNotFoundError("no main")
            mock_pkg.files.return_value.joinpath.return_value = mock_source
            _copy_example_saga("some/template", tmp_path)
            # simple path should create example_saga.py
            assert (tmp_path / "example_saga.py").exists()


# ---------------------------------------------------------------------------
# _copy_dir_resource
# ---------------------------------------------------------------------------


class TestCopyDirResource:
    def test_creates_files(self, tmp_path):
        from sagaz.cli._init_handlers import _copy_dir_resource

        mock_file = MagicMock()
        mock_file.is_dir.return_value = False
        mock_file.name = "config.yaml"
        mock_file.read_text.return_value = "key: value"

        mock_traversable = MagicMock()
        mock_traversable.iterdir.return_value = [mock_file]

        with patch("sagaz.cli._init_handlers.pkg_resources") as mock_pkg, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = _noop
            mock_pkg.files.return_value.joinpath.return_value = mock_traversable
            target = str(tmp_path / "output")
            _copy_dir_resource("some/dir", target)
            assert (tmp_path / "output" / "config.yaml").read_text() == "key: value"

    def test_handles_binary_file(self, tmp_path):
        from sagaz.cli._init_handlers import _copy_dir_resource

        mock_file = MagicMock()
        mock_file.is_dir.return_value = False
        mock_file.name = "data.bin"
        mock_file.read_text.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "reason")
        mock_file.read_bytes.return_value = b"\x00\x01\x02"

        mock_traversable = MagicMock()
        mock_traversable.iterdir.return_value = [mock_file]

        with patch("sagaz.cli._init_handlers.pkg_resources") as mock_pkg, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = _noop
            mock_pkg.files.return_value.joinpath.return_value = mock_traversable
            target = str(tmp_path / "output")
            _copy_dir_resource("some/dir", target)
            assert (tmp_path / "output" / "data.bin").read_bytes() == b"\x00\x01\x02"

    def test_recurses_into_subdirs(self, tmp_path):
        """_copy_dir_resource recurses into sub-directories."""
        from sagaz.cli import _init_handlers as m

        mock_sub = MagicMock()
        mock_sub.is_dir.return_value = True
        mock_sub.name = "subdir"

        mock_top = MagicMock()
        mock_top.iterdir.return_value = [mock_sub]

        mock_empty = MagicMock()
        mock_empty.iterdir.return_value = []

        # First joinpath call returns top (has subdir), second returns empty dir
        mock_files = MagicMock()
        mock_files.joinpath.side_effect = [mock_top, mock_empty]

        with patch.object(m, "pkg_resources") as mock_pkg, patch(
            "sagaz.cli._init_handlers.click"
        ):
            mock_pkg.files.return_value = mock_files
            m._copy_dir_resource("root/dir", str(tmp_path / "out"))
            # joinpath called twice: once for root/dir, once for root/dir/subdir
            assert mock_files.joinpath.call_count == 2

    def test_not_found_returns_silently(self):
        from sagaz.cli._init_handlers import _copy_dir_resource

        with patch("sagaz.cli._init_handlers.pkg_resources") as mock_pkg:
            mock_traversable = MagicMock()
            mock_traversable.iterdir.side_effect = FileNotFoundError("no dir")
            mock_pkg.files.return_value.joinpath.return_value = mock_traversable
            # Should not raise
            _copy_dir_resource("nonexistent/dir", "/tmp/output")

    def test_exception_swallowed(self):
        from sagaz.cli._init_handlers import _copy_dir_resource

        with patch("sagaz.cli._init_handlers.pkg_resources") as mock_pkg:
            mock_pkg.files.side_effect = Exception("unexpected")
            # Should not raise
            _copy_dir_resource("some/dir", "/tmp/output")


# ---------------------------------------------------------------------------
# _copy_resource
# ---------------------------------------------------------------------------


class TestCopyResource:
    def test_success(self, tmp_path):
        from sagaz.cli._init_handlers import _copy_resource

        with patch("sagaz.cli._init_handlers.pkg_resources") as mock_pkg, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = _noop
            mock_pkg.files.return_value.joinpath.return_value.read_text.return_value = (
                "content"
            )
            _copy_resource("some/file.yaml", str(tmp_path / "out.yaml"))
            assert (tmp_path / "out.yaml").read_text() == "content"

    def test_error_echoes_message(self):
        from sagaz.cli._init_handlers import _copy_resource

        with patch("sagaz.cli._init_handlers.pkg_resources") as mock_pkg, patch(
            "sagaz.cli._init_handlers.click"
        ) as mock_click:
            mock_click.echo = MagicMock()
            mock_pkg.files.side_effect = Exception("pkg error")
            _copy_resource("bad/path.yaml", "/tmp/out.yaml")
            mock_click.echo.assert_called_once()
            msg = mock_click.echo.call_args[0][0]
            assert "ERROR" in msg


# ---------------------------------------------------------------------------
# ImportError path: console = None
# ---------------------------------------------------------------------------


class TestConsoleImportError:
    def test_console_none_when_rich_unavailable(self):
        """Lines 23-24: ImportError → console = None."""
        import importlib

        import sagaz.cli._init_handlers as m

        # Simulate the ImportError branch by setting console to None
        original_console = m.console
        m.console = None
        try:
            # Functions that guard on console should work fine
            from sagaz.cli._init_handlers import _log_local_init_start

            _log_local_init_start("redis", False, "postgresql", dev_mode=False)
        finally:
            m.console = original_console
