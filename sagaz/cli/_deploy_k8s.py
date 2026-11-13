"""Kubernetes deployment initialization."""

import shutil
from pathlib import Path

import click

from sagaz.cli._deploy_resources import _copy_dir_resource, _copy_resource

try:
    from rich.console import Console

    console: Console | None = Console()
except ImportError:
    console = None


def _init_k8s(
    with_observability: bool,
    with_benchmarks: bool,
    with_ha: bool = False,
    separate_outbox: bool = False,
    oltp_storage: str = "postgresql",
    outbox_storage: str = "same",
):
    """Copy Kubernetes manifests from the library to the current directory."""
    _log_k8s_init_start(with_ha, oltp_storage)

    if not _prepare_k8s_directory():
        return

    try:
        _copy_k8s_manifests(with_ha, separate_outbox, oltp_storage)
        _copy_k8s_observability(with_observability)
        _copy_k8s_benchmarks(with_benchmarks)
        _log_k8s_init_complete(with_ha)
    except Exception as e:
        click.echo(f"Error copying manifests: {e}")


def _log_k8s_init_start(with_ha: bool, oltp_storage: str):
    """Log the start of K8s initialization."""
    if not console:
        return
    ha_msg = " with [bold yellow]HA PostgreSQL[/bold yellow]" if with_ha else ""
    console.print(
        f"Copying Kubernetes manifests{ha_msg} (storage:"
        f" [bold cyan]{oltp_storage}[/bold cyan]) to"
        f" [bold cyan]./k8s[/bold cyan]..."
    )


def _prepare_k8s_directory() -> bool:
    """Prepare k8s directory, prompting for overwrite if exists. Returns False to abort."""
    if Path("k8s").exists():
        if not click.confirm(
            "Directory [bold yellow]k8s/[/bold yellow] already exists. Overwrite?"
        ):
            click.echo("Aborted.")
            return False
        shutil.rmtree("k8s")
    Path("k8s").mkdir(exist_ok=True)
    return True


def _copy_k8s_manifests(
    with_ha: bool, separate_outbox: bool = False, oltp_storage: str = "postgresql"
):
    """Copy base Kubernetes manifests."""
    if oltp_storage == "postgresql":
        if with_ha:
            _copy_resource("k8s/postgresql-ha.yaml", "k8s/postgresql-ha.yaml")
            _copy_resource("k8s/pgbouncer.yaml", "k8s/pgbouncer.yaml")
            click.echo("  CREATE k8s/postgresql-ha.yaml (StatefulSet with replicas)")
            click.echo("  CREATE k8s/pgbouncer.yaml (Connection pooling)")
            Path("k8s/partitioning").mkdir(exist_ok=True)
            _copy_dir_resource("local/postgres/partitioning", "k8s/partitioning")
        else:
            _copy_resource("k8s/postgresql.yaml", "k8s/postgresql.yaml")
    elif oltp_storage == "in-memory":
        click.echo("  SKIP postgresql (using in-memory storage)")

    # Separate outbox database if requested
    if separate_outbox:
        _copy_resource("k8s/outbox-postgresql.yaml", "k8s/outbox-postgresql.yaml")
        click.echo("  CREATE k8s/outbox-postgresql.yaml (Separate outbox database)")

    # Copy base manifests
    for manifest in [
        "outbox-worker.yaml",
        "configmap.yaml",
        "secrets-example.yaml",
        "migration-job.yaml",
    ]:
        _copy_resource(f"k8s/{manifest}", f"k8s/{manifest}")


def _copy_k8s_observability(with_observability: bool):
    """Copy K8s observability manifests if enabled."""
    if with_observability:
        _copy_resource("k8s/prometheus-monitoring.yaml", "k8s/prometheus-monitoring.yaml")
        _copy_resource("k8s/jaeger-tracing.yaml", "k8s/jaeger-tracing.yaml")
        _copy_dir_resource("k8s/monitoring", "k8s/monitoring")
    else:
        click.echo("  SKIP k8s/monitoring (observability disabled)")


def _copy_k8s_benchmarks(with_benchmarks: bool):
    """Copy K8s benchmark configs if enabled."""
    if with_benchmarks:
        _create_k8s_benchmark_config()
    else:
        click.echo("  SKIP k8s/benchmark (use --with-benchmarks to include)")


def _log_k8s_init_complete(with_ha: bool):
    """Log completion message for K8s initialization."""
    if not console:
        return

    console.print("[bold green]Kubernetes manifests copied successfully![/bold green]")
    if with_ha:
        console.print("\n[bold yellow]HA PostgreSQL Services:[/bold yellow]")
        console.print("  - postgresql-primary:5432 (write traffic)")
        console.print("  - postgresql-read:5432 (read traffic, load-balanced)")
        console.print("  - pgbouncer-rw:6432 (write pool)")
        console.print("  - pgbouncer-ro:6433 (read pool)")


def _create_k8s_benchmark_config():
    """Create Kubernetes benchmark job configuration."""
    Path("k8s/benchmark").mkdir(parents=True, exist_ok=True)

    benchmark_job = """apiVersion: batch/v1
kind: Job
metadata:
  name: sagaz-benchmark
  namespace: sagaz
spec:
  template:
    spec:
      containers:
      - name: benchmark
        image: sagaz/sagaz:latest
        command: ["python", "-m", "pytest"]
        args:
          - "tests/test_performance.py"
          - "-v"
          - "-m"
          - "performance"
          - "--tb=short"
        env:
        - name: POSTGRES_URL
          valueFrom:
            secretKeyRef:
              name: sagaz-secrets
              key: postgres-url
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: sagaz-secrets
              key: redis-url
      restartPolicy: Never
  backoffLimit: 1
"""
    Path("k8s/benchmark/job.yaml").write_text(benchmark_job)
    click.echo("  CREATE k8s/benchmark/job.yaml")

    # Create stress test job
    stress_job = """apiVersion: batch/v1
kind: Job
metadata:
  name: sagaz-stress-test
  namespace: sagaz
spec:
  template:
    spec:
      containers:
      - name: stress
        image: sagaz/sagaz:latest
        command: ["python", "-m", "pytest"]
        args:
          - "tests/test_performance.py"
          - "-v"
          - "-m"
          - "stress"
          - "--tb=short"
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2"
      restartPolicy: Never
  backoffLimit: 1
"""
    Path("k8s/benchmark/stress-job.yaml").write_text(stress_job)
    click.echo("  CREATE k8s/benchmark/stress-job.yaml")
