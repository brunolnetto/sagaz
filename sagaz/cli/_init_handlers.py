"""
Deployment initialization handlers for the Sagaz CLI.

Re-exports the helper functions for initialising each supported deployment mode,
which live in one private module per deployment target:
- Local  (Docker Compose)          -> ``_deploy_local``
- Self-hosted (on-premise / systemd) -> ``_deploy_selfhost``
- Kubernetes                       -> ``_deploy_k8s``
- Hybrid (local storage + cloud broker) and Benchmarks -> ``_deploy_hybrid``
- Resource copy utilities          -> ``_deploy_resources``
"""

from sagaz.cli._deploy_hybrid import _init_benchmarks, _init_hybrid
from sagaz.cli._deploy_k8s import (
    _copy_k8s_benchmarks,
    _copy_k8s_manifests,
    _copy_k8s_observability,
    _create_k8s_benchmark_config,
    _init_k8s,
    _log_k8s_init_complete,
    _log_k8s_init_start,
    _prepare_k8s_directory,
)
from sagaz.cli._deploy_local import (
    _copy_docker_compose_files,
    _create_inmemory_docker_compose,
    _get_broker_config,
    _init_docker_compose,
    _init_local,
    _init_monitoring,
    _log_local_init_complete,
    _log_local_init_start,
)
from sagaz.cli._deploy_resources import (
    _copy_dir_resource,
    _copy_example_saga,
    _copy_resource,
    _resources,
)
from sagaz.cli._deploy_selfhost import (
    _create_selfhost_monitoring,
    _create_systemd_service,
    _init_selfhost,
)

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
    "_log_local_init_start",
    "_prepare_k8s_directory",
    "_resources",
]
