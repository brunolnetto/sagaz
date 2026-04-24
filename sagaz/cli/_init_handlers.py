"""
Deployment initialization handlers for the Sagaz CLI.
Modified to maintain full backward compatibility with tests (v1.6.1).
"""

from .init.k8s import (
    _copy_k8s_benchmarks,
    _copy_k8s_manifests,
    _copy_k8s_observability,
    _create_k8s_benchmark_config,
    _log_k8s_init_complete,
    _log_k8s_init_start,
    _prepare_k8s_directory,
)
from .init.k8s import (
    init_k8s as _init_k8s,
)
from .init.local import (
    _copy_docker_compose_files,
    _create_inmemory_docker_compose,
    _get_broker_config,
    _init_docker_compose,
    _init_monitoring,
    _log_local_init_complete,
    _log_local_init_start,
)
from .init.local import (
    init_local as _init_local,
)
from .init.others import (
    _create_selfhost_monitoring,
    _create_systemd_service,
)
from .init.others import (
    init_benchmarks as _init_benchmarks,
)
from .init.others import (
    init_hybrid as _init_hybrid,
)
from .init.others import (
    init_selfhost as _init_selfhost,
)
from .init.utils import console
from .init.utils import copy_dir_resource as _copy_dir_resource
from .init.utils import copy_example_saga as _copy_example_saga
from .init.utils import copy_resource as _copy_resource

# Aliases for Click group in init.py if they expect no underscore
init_local = _init_local
init_k8s = _init_k8s
init_selfhost = _init_selfhost
init_hybrid = _init_hybrid
init_benchmarks = _init_benchmarks

__all__ = [
    "_copy_dir_resource",
    "_copy_docker_compose_files",
    "_copy_example_saga",
    "_copy_k8s_benchmarks",
    "_copy_k8s_manifests",
    "_copy_k8s_observability",
    "_copy_resource",
    "_create_inmemory_docker_compose",
    "_create_k8s_benchmark_config",
    "_create_selfhost_monitoring",
    "_create_systemd_service",
    "_get_broker_config",
    "_init_benchmarks",
    "_init_docker_compose",
    "_init_hybrid",
    "_init_k8s",
    "_init_local",
    "_init_monitoring",
    "_init_selfhost",
    "_log_k8s_init_complete",
    "_log_k8s_init_start",
    "_log_local_init_complete",
    # Internal ones for tests
    "_log_local_init_start",
    "_prepare_k8s_directory",
    "console",
]
