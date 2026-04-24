"""
Kubernetes initialization handlers.
"""

import shutil
from pathlib import Path

from . import utils


def init_k8s(
    with_observability: bool,
    with_benchmarks: bool,
    with_ha: bool = False,
    separate_outbox: bool = False,
    oltp_storage: str = "postgresql",
    outbox_storage: str = "same",
):
    """Copy Kubernetes manifests."""
    try:
        _log_k8s_init_start(with_ha, oltp_storage)
        if not _prepare_k8s_directory(): return

        _copy_k8s_manifests(with_ha, separate_outbox, oltp_storage)
        _copy_k8s_observability(with_observability)
        _copy_k8s_benchmarks(with_benchmarks)
        _log_k8s_init_complete(with_ha)
    except Exception as e:
        utils.click.echo(f"  ERROR: {e}")


def _log_k8s_init_start(with_ha: bool, oltp_storage: str):
    if not utils.console: return
    ha_msg = " with [bold yellow]HA PostgreSQL[/bold yellow]" if with_ha else ""
    utils.console.print(f"Copying Kubernetes manifests{ha_msg} (storage: [bold cyan]{oltp_storage}[/bold cyan])...")


def _prepare_k8s_directory() -> bool:
    if Path("k8s").exists():
        if not utils.click.confirm("Directory k8s/ already exists. Overwrite?"):
            return False
        shutil.rmtree("k8s")
    Path("k8s").mkdir(exist_ok=True)
    return True


def _copy_k8s_manifests(with_ha: bool, separate_outbox: bool = False, oltp_storage: str = "postgresql"):
    if oltp_storage == "postgresql":
        if with_ha:
            utils.copy_resource("k8s/postgresql-ha.yaml", "k8s/postgresql-ha.yaml")
            utils.copy_resource("k8s/pgbouncer.yaml", "k8s/pgbouncer.yaml")
            utils.copy_dir_resource("local/postgres/partitioning", "k8s/partitioning")
        else:
            utils.copy_resource("k8s/postgresql.yaml", "k8s/postgresql.yaml")

    if separate_outbox:
        utils.copy_resource("k8s/outbox-postgresql.yaml", "k8s/outbox-postgresql.yaml")

    for manifest in ["outbox-worker.yaml", "configmap.yaml", "secrets-example.yaml", "migration-job.yaml"]:
        utils.copy_resource(f"k8s/{manifest}", f"k8s/{manifest}")


def _copy_k8s_observability(with_observability: bool):
    if with_observability:
        utils.copy_resource("k8s/prometheus-monitoring.yaml", "k8s/prometheus-monitoring.yaml")
        utils.copy_resource("k8s/jaeger-tracing.yaml", "k8s/jaeger-tracing.yaml")
        utils.copy_dir_resource("k8s/monitoring", "k8s/monitoring")


def _copy_k8s_benchmarks(with_benchmarks: bool):
    if with_benchmarks:
        _create_k8s_benchmark_config()
    else:
        utils.click.echo("  SKIP benchmarks")


def _log_k8s_init_complete(with_ha: bool):
    if not utils.console: return
    utils.console.print("[bold green]Kubernetes manifests copied successfully![/bold green]")
    if with_ha:
        utils.console.print("  - [bold yellow]HA PostgreSQL[/bold yellow] manifests included (port 5432)")


def _create_k8s_benchmark_config():
    Path("k8s/benchmark").mkdir(parents=True, exist_ok=True)
    job = "apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: sagaz-benchmark"
    Path("k8s/benchmark/job.yaml").write_text(job)
    stress = "apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: sagaz-stress-test"
    Path("k8s/benchmark/stress-job.yaml").write_text(stress)
