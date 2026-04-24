"""
Deployment initialization handlers for the Sagaz CLI.
Modified to maintain full backward compatibility with tests (v1.6.1).
"""

from .init.local import (
    init_local as _init_local,
    _log_local_init_start,
    _init_docker_compose,
    _copy_docker_compose_files,
    _get_broker_config,
    _create_inmemory_docker_compose,
    _init_monitoring,
    _log_local_init_complete,
)
from .init.k8s import (
    init_k8s as _init_k8s,
    _log_k8s_init_start,
    _prepare_k8s_directory,
    _copy_k8s_manifests,
    _copy_k8s_observability,
    _copy_k8s_benchmarks,
    _log_k8s_init_complete,
    _create_k8s_benchmark_config,
)
from .init.others import (
    init_selfhost as _init_selfhost,
    init_hybrid as _init_hybrid,
    init_benchmarks as _init_benchmarks,
    _create_systemd_service,
    _create_selfhost_monitoring,
)
from .init.utils import (
    copy_resource as _copy_resource, 
    copy_dir_resource as _copy_dir_resource,
    copy_example_saga as _copy_example_saga,
    console
)

# Aliases for Click group in init.py if they expect no underscore
init_local = _init_local
init_k8s = _init_k8s
init_selfhost = _init_selfhost
init_hybrid = _init_hybrid
init_benchmarks = _init_benchmarks

__all__ = [
    "_init_local",
    "_init_selfhost",
    "_init_k8s",
    "_init_hybrid",
    "_init_benchmarks",
    "_copy_resource",
    "_copy_dir_resource",
    "_copy_example_saga",
    "console",
    # Internal ones for tests
    "_log_local_init_start",
    "_init_docker_compose",
    "_copy_docker_compose_files",
    "_get_broker_config",
    "_create_inmemory_docker_compose",
    "_init_monitoring",
    "_log_local_init_complete",
    "_log_k8s_init_start",
    "_prepare_k8s_directory",
    "_copy_k8s_manifests",
    "_copy_k8s_observability",
    "_copy_k8s_benchmarks",
    "_log_k8s_init_complete",
    "_create_k8s_benchmark_config",
    "_create_systemd_service",
    "_create_selfhost_monitoring",
]
