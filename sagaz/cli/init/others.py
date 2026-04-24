"""
Self-hosted, Hybrid, and Benchmark initialization handlers.
"""

from pathlib import Path
from . import utils


from .local import init_local
from .k8s import init_k8s

def init_selfhost(broker: str, with_observability: bool, separate_outbox: bool = False):
    """Create self-hosted setup scripts."""
    if utils.console: utils.console.print("Creating [bold yellow]self-hosted[/bold yellow] setup scripts...")
    Path("selfhost").mkdir(exist_ok=True)
    _create_systemd_service("sagaz-worker", "Sagaz Worker Service", "python -m sagaz.worker")
    if with_observability:
        _create_selfhost_monitoring()
    
    env_content = f"SAGAZ_BROKER={broker}\n"
    if separate_outbox: env_content += "OUTBOX_URL=postgresql://localhost:5432/outbox\n"
    if broker == "kafka": env_content += "KAFKA_BOOTSTRAP_SERVERS=localhost:9092\n"
    elif broker == "rabbitmq": env_content += "RABBITMQ_URL=amqp://sagaz:sagaz@localhost:5672/\n"
    
    Path("selfhost/sagaz.env").write_text(env_content)
    Path("selfhost/install.sh").write_text("#!/bin/bash\n# Sagaz installation script\n")


def _create_systemd_service(name: str, description: str, command: str):
    content = f"[Unit]\nDescription={description}\n\n[Service]\nExecStart={command}\n"
    Path(f"selfhost/{name}.service").write_text(content)


def _create_selfhost_monitoring():
    utils.copy_resource("local/redis/monitoring/prometheus.yml", "selfhost/prometheus.yml")


def init_hybrid(broker: str = "redis", oltp_storage: str = "postgresql"):
    """Create hybrid deployment setup."""
    if utils.console: utils.console.print("Creating [bold yellow]hybrid[/bold yellow] deployment setup...")
    
    hybrid_dir = Path("hybrid")
    hybrid_dir.mkdir(exist_ok=True)
    
    # Create README.md
    (hybrid_dir / "README.md").write_text("# Sagaz Hybrid Deployment\n\nSetup for hybrid cloud/local environment.\n")
    
    # Create hybrid.env
    broker_url = "localhost:6379" if broker == "redis" else "localhost:9092"
    if broker == "rabbitmq": broker_url = "amqp://sagaz:sagaz@localhost:5672/"
    
    env_content = [
        f"SAGAZ_BROKER={broker}",
        f"BROKER_URL={broker_url}",
    ]
    if oltp_storage == "postgresql":
        env_content.append("DATABASE_URL=postgresql://sagaz:sagaz@localhost:5432/sagaz")
    
    (hybrid_dir / "hybrid.env").write_text("\n".join(env_content) + "\n")
    
    # Create docker-compose.yaml via init_local (using a temporary change of directory)
    if oltp_storage != "in-memory":
        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(hybrid_dir)
            init_local(broker, with_observability=True, oltp_storage=oltp_storage)
        finally:
            os.chdir(old_cwd)


def init_benchmarks():
    """Create benchmark environment."""
    if utils.console: utils.console.print("Creating [bold yellow]benchmark[/bold yellow] environment...")
    
    # Create directory
    bench_dir = Path("benchmarks")
    bench_dir.mkdir(exist_ok=True)
    
    init_local("redis", with_observability=False)
    init_k8s(with_observability=False, with_benchmarks=True)
    
    # Create run.sh
    run_sh = bench_dir / "run.sh"
    content = "#!/bin/bash\n# Sagaz Benchmark runner\n# Runs profiling and performance tests\npytest -m benchmark\nkubectl apply -f k8s/benchmark/job.yaml\n"
    run_sh.write_text(content)
    run_sh.chmod(0o755)
