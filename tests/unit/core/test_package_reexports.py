"""Packages whose logic lives in private modules keep one source of truth.

The ``__init__.py`` of these packages only re-exports; these tests pin the
behaviour that callers rely on: identical objects across import paths, live
module-level singletons and unchanged logger names.
"""

import importlib
import logging

import pytest

import sagaz
import sagaz.core.config as config_pkg
import sagaz.core.env as env_pkg
from sagaz.core.config import _config
from sagaz.core.env import _manager


@pytest.mark.parametrize(
    ("package", "private_module"),
    [
        ("sagaz.core.compliance", "sagaz.core.compliance._manager"),
        ("sagaz.core.config", "sagaz.core.config._config"),
        ("sagaz.core.context", "sagaz.core.context._context"),
        ("sagaz.core.decorators", "sagaz.core.decorators._saga"),
        ("sagaz.core.env", "sagaz.core.env._manager"),
        ("sagaz.core.exceptions", "sagaz.core.exceptions._saga"),
        ("sagaz.core.listeners", "sagaz.core.listeners._defaults"),
        ("sagaz.core.outbox.brokers", "sagaz.core.outbox.brokers._lazy"),
        ("sagaz.core.replay", "sagaz.core.replay._models"),
        ("sagaz.core.saga", "sagaz.core.saga._saga"),
        ("sagaz.demonstrations", "sagaz.demonstrations._discovery"),
    ],
)
def test_package_reexports_are_the_private_module_objects(package, private_module):
    pkg = importlib.import_module(package)
    mod = importlib.import_module(private_module)
    shared = [name for name in pkg.__all__ if hasattr(mod, name)]
    assert shared, f"{package} re-exports nothing from {private_module}"
    for name in shared:
        assert getattr(pkg, name) is getattr(mod, name), name


def test_top_level_saga_classes_are_the_moved_classes():
    from sagaz.core.decorators._saga import Saga as DeclarativeSaga
    from sagaz.core.saga._saga import Saga as ImperativeSaga

    assert sagaz.Saga is DeclarativeSaga
    assert sagaz.core.saga.Saga is ImperativeSaga


class TestGlobalConfigSingleton:
    def test_configure_is_visible_from_every_import_path(self):
        previous = _config._global_config
        try:
            new_config = config_pkg.SagaConfig()
            config_pkg.configure(new_config)

            assert _config._global_config is new_config
            assert config_pkg._global_config is new_config
            assert config_pkg.get_config() is new_config
            assert sagaz.get_config() is new_config
        finally:
            _config._global_config = previous

    def test_private_state_is_listed_and_unknown_names_still_fail(self):
        assert "_global_config" in dir(config_pkg)
        assert "SagaConfig" in dir(config_pkg)
        with pytest.raises(AttributeError, match="no attribute 'does_not_exist'"):
            config_pkg.does_not_exist  # noqa: B018


class TestGlobalEnvSingleton:
    def test_get_env_is_visible_from_every_import_path(self):
        previous = _manager._global_env
        try:
            _manager._global_env = None
            env = env_pkg.get_env()

            assert env_pkg._global_env is env
            assert _manager._global_env is env
            assert env_pkg.get_env() is env
        finally:
            _manager._global_env = previous

    def test_private_state_is_listed_and_unknown_names_still_fail(self):
        assert "_global_env" in dir(env_pkg)
        assert "EnvManager" in dir(env_pkg)
        with pytest.raises(AttributeError, match="no attribute 'does_not_exist'"):
            env_pkg.does_not_exist  # noqa: B018


@pytest.mark.parametrize(
    ("module", "logger_name"),
    [
        ("sagaz.core.config._config", "sagaz.core.config"),
        ("sagaz.core.saga._saga", "sagaz.core.saga"),
        ("sagaz.core.decorators._saga", "sagaz.core.decorators"),
    ],
)
def test_logger_names_are_unchanged(module, logger_name):
    logger = importlib.import_module(module).logger
    assert logger is logging.getLogger(logger_name)
