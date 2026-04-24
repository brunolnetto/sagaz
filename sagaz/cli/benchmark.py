"""
Performance benchmarking commands.
"""

import subprocess
from pathlib import Path
import click

try:
    from rich.console import Console
    from rich.panel import Panel
    console: Console | None = Console()
except ImportError:
    console = None
    Panel = None


@click.command(name="benchmark")
@click.option(
    "--profile",
    type=click.Choice(["local", "production", "stress", "full"]),
    default="local",
    help="Benchmark profile",
)
@click.option("--output", type=click.Path(), help="Output file for results (JSON)")
@click.option("--quick", is_flag=True, help="Quick sanity check (minimal iterations)")
def benchmark_cmd(profile: str, output: str, quick: bool):
    """
    Run performance benchmarks.

    Profiles:
        local       Fast tests for development (default)
        production  Comprehensive tests with production config
        stress      High concurrency and endurance tests
        full        All benchmark tests

    Examples:
        sagaz benchmark                  # Quick local tests
        sagaz benchmark --profile stress # Stress testing
        sagaz benchmark --output out.json # Save results
    """
    if console and Panel:
        console.print(
            Panel.fit(
                f"[bold blue]Sagaz Performance Benchmark[/bold blue]\n"
                f"Profile: [cyan]{profile}[/cyan]",
                border_style="blue",
            )
        )

    # Build pytest command
    cmd = ["python", "-m", "pytest", "tests/test_performance.py", "-v", "--tb=short"]

    if profile == "local":
        cmd.extend(["-m", "performance and not slow"])
    elif profile == "production":
        cmd.extend(["-m", "performance"])
    elif profile == "stress":
        cmd.extend(["-m", "stress"])
    # full = no marker filter

    if quick:
        # Override to minimal test
        cmd = [
            "python",
            "-c",
            """
import asyncio
from sagaz import Saga, action

class TestSaga(Saga):
    saga_name = "benchmark-quick"

    @action("step1")
    async def step1(self, ctx):
        return {"done": True}

async def main():
    import time
    start = time.perf_counter()
    for _ in range(10):
        saga = TestSaga()
        await saga.run({})
    elapsed = time.perf_counter() - start
    throughput = 10 / elapsed
    print(f"Quick benchmark: {throughput:.1f} sagas/sec")

async def main_run():
    await main()

if __name__ == '__main__':
    asyncio.run(main_run())
""",
        ]

    # Run benchmark
    result = subprocess.run(cmd, capture_output=output is not None, check=False)

    if output and result.returncode == 0:
        Path(output).write_text(result.stdout.decode() if result.stdout else "", encoding="utf-8")
        click.echo(f"Results saved to {output}")

    return result.returncode
