#!/usr/bin/env python3
"""
High-Throughput Benchmark for Sagaz Outbox Pattern

This demonstration benchmarks the MAXIMUM throughput achievable locally by:
1. Using in-memory broker (bypasses network overhead)
2. Batch database operations
3. Parallel inserts using COPY command
4. Direct database processing simulation

This measures the theoretical maximum your machine can handle.

Prerequisites:
    PostgreSQL must be reachable. Set POSTGRES_URL environment variable
    or use the default: postgresql://saga_user:saga_password@localhost:5433/saga_db

Usage:
    sagaz demo run high_throughput
    sagaz demo run high_throughput -- --events 100000 --workers 20
    python -m sagaz.demonstrations.high_throughput.main --events 50000
"""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime

try:
    import asyncpg
except ImportError:
    print("Please install asyncpg: pip install asyncpg")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

DATABASE_URL = os.getenv(
    "POSTGRES_URL", "postgresql://saga_user:saga_password@localhost:5433/saga_db"
)

console = Console() if RICH_AVAILABLE else None


class HighThroughputBenchmark:
    """Optimized benchmark for maximum throughput testing."""

    def __init__(
        self,
        database_url: str = DATABASE_URL,
        num_workers: int = 20,
        batch_size: int = 1000,
    ):
        self.database_url = database_url
        self.num_workers = num_workers
        self.batch_size = batch_size
        self.pool: asyncpg.Pool | None = None

        self.events_inserted = 0
        self.events_processed = 0
        self.insert_start_time = 0
        self.process_start_time = 0
        self._lock = asyncio.Lock()
        self._stop = False

    async def connect(self):
        """Connect with optimized pool settings."""
        pool_size = min(self.num_workers, 10)
        self.pool = await asyncpg.create_pool(
            self.database_url,
            min_size=2,
            max_size=pool_size,
            command_timeout=60,
            statement_cache_size=100,
        )

        if RICH_AVAILABLE:
            console.print("[green]✓[/green] Connected to PostgreSQL")

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()

    async def clear_outbox(self):
        """Clear all events for clean benchmark."""
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM saga_outbox")
            if RICH_AVAILABLE:
                console.print(f"[dim]Cleared outbox: {result}[/dim]")

    async def batch_insert_with_copy(
        self,
        num_events: int,
        batch_size: int = 10000,
    ) -> float:
        """Insert events using PostgreSQL COPY for maximum speed."""
        self.insert_start_time = time.time()
        self.events_inserted = 0

        async with self.pool.acquire() as conn:
            for batch_start in range(0, num_events, batch_size):
                batch_count = min(batch_size, num_events - batch_start)

                records = []
                for i in range(batch_count):
                    event_id = uuid.uuid4()
                    saga_id = str(uuid.uuid4())
                    aggregate_id = str(uuid.uuid4())
                    payload = json.dumps(
                        {
                            "index": batch_start + i,
                            "data": f"Event {batch_start + i}",
                            "ts": datetime.now(UTC).isoformat(),
                        }
                    )
                    headers = json.dumps({"batch": batch_start // batch_size})

                    records.append(
                        (
                            event_id,
                            saga_id,
                            "benchmark",
                            aggregate_id,
                            "BenchmarkEvent",
                            payload,
                            headers,
                            "pending",
                            datetime.now(UTC),
                            0,
                        )
                    )

                await conn.copy_records_to_table(
                    "saga_outbox",
                    records=records,
                    columns=[
                        "event_id",
                        "saga_id",
                        "aggregate_type",
                        "aggregate_id",
                        "event_type",
                        "payload",
                        "headers",
                        "status",
                        "created_at",
                        "retry_count",
                    ],
                )

                self.events_inserted += batch_count

                if RICH_AVAILABLE and batch_start % 10000 == 0:
                    elapsed = time.time() - self.insert_start_time
                    rate = self.events_inserted / elapsed if elapsed > 0 else 0
                    console.print(
                        f"  [cyan]Inserted:[/cyan] {self.events_inserted:,} | "
                        f"[green]Rate:[/green] {rate:,.0f}/sec"
                    )

        return time.time() - self.insert_start_time

    async def process_batch_worker(self, worker_id: int):
        """Simulated high-speed worker that processes events."""
        while not self._stop:
            async with self.pool.acquire() as conn:
                events = await conn.fetch(
                    """
                    UPDATE saga_outbox
                    SET status = 'claimed',
                        worker_id = $1,
                        claimed_at = NOW()
                    WHERE event_id IN (
                        SELECT event_id FROM saga_outbox
                        WHERE status = 'pending'
                        LIMIT $2
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING event_id
                """,
                    f"worker-{worker_id}",
                    self.batch_size,
                )

                if not events:
                    await asyncio.sleep(0.01)
                    continue

                event_ids = [e["event_id"] for e in events]

                await conn.execute(
                    """
                    UPDATE saga_outbox
                    SET status = 'sent', sent_at = NOW()
                    WHERE event_id = ANY($1::uuid[])
                """,
                    event_ids,
                )

                async with self._lock:
                    self.events_processed += len(event_ids)

    async def _monitor_progress_rich(self, total_events: int) -> bool:
        """Monitor progress with Rich UI."""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            TextColumn("[cyan]{task.fields[rate]}/sec"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"Processing with {self.num_workers} workers...", total=total_events, rate="0"
            )

            while self.events_processed < total_events:
                await asyncio.sleep(0.5)
                elapsed = time.time() - self.process_start_time
                rate = self.events_processed / elapsed if elapsed > 0 else 0
                progress.update(task, completed=self.events_processed, rate=f"{rate:,.0f}")

                if elapsed > 120 and self.events_processed < total_events * 0.9:
                    console.print("[red]Warning: Processing appears stalled[/red]")
                    return True
        return False

    async def _monitor_progress_simple(self, total_events: int):
        """Monitor progress with simple output."""
        while self.events_processed < total_events:
            await asyncio.sleep(1)
            elapsed = time.time() - self.process_start_time
            rate = self.events_processed / elapsed if elapsed > 0 else 0
            print(
                f"  Processed: {self.events_processed:,}/{total_events:,} | Rate: {rate:,.0f}/sec",
                end="\r",
            )

    async def _stop_workers(self, workers: list):
        """Stop all worker tasks."""
        self._stop = True
        await asyncio.sleep(0.1)

        for w in workers:
            w.cancel()
            try:
                await w
            except asyncio.CancelledError:
                pass

    async def run_processing_workers(self, total_events: int):
        """Run parallel workers to process events."""
        self.process_start_time = time.time()
        self.events_processed = 0
        self._stop = False

        workers = [
            asyncio.create_task(self.process_batch_worker(i)) for i in range(self.num_workers)
        ]

        if RICH_AVAILABLE:
            await self._monitor_progress_rich(total_events)
        else:
            await self._monitor_progress_simple(total_events)

        await self._stop_workers(workers)

        return time.time() - self.process_start_time

    async def get_stats(self) -> dict:
        """Get current outbox statistics."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE status = 'claimed') as claimed,
                    COUNT(*) FILTER (WHERE status = 'sent') as sent,
                    COUNT(*) as total
                FROM saga_outbox
            """)
            return dict(row)


async def run_benchmark(
    num_events: int = 100000,
    num_workers: int = 20,
    batch_size: int = 1000,
    db_url: str = DATABASE_URL,
):
    """Run the high-throughput benchmark."""

    if RICH_AVAILABLE:
        console.print(
            Panel.fit(
                f"[bold]High-Throughput Outbox Benchmark[/bold]\n"
                f"Events: {num_events:,} | Workers: {num_workers} | Batch: {batch_size}",
                border_style="bold blue",
            )
        )
    else:
        print("\n=== High-Throughput Benchmark ===")
        print(f"Events: {num_events:,} | Workers: {num_workers} | Batch: {batch_size}")

    benchmark = HighThroughputBenchmark(
        database_url=db_url,
        num_workers=num_workers,
        batch_size=batch_size,
    )

    try:
        await benchmark.connect()

        await benchmark.clear_outbox()

        if RICH_AVAILABLE:
            console.rule("[bold cyan]Phase 1: Bulk Insert (COPY)")
        else:
            print("\n--- Phase 1: Bulk Insert ---")

        insert_time = await benchmark.batch_insert_with_copy(
            num_events=num_events,
            batch_size=10000,
        )
        insert_rate = num_events / insert_time

        if RICH_AVAILABLE:
            console.print(f"[green]✓[/green] Inserted {num_events:,} events in {insert_time:.2f}s")
            console.print(f"  [bold]Insert Rate:[/bold] {insert_rate:,.0f} events/sec")
        else:
            print(f"Inserted {num_events:,} events in {insert_time:.2f}s ({insert_rate:,.0f}/sec)")

        if RICH_AVAILABLE:
            console.rule("[bold cyan]Phase 2: Process Events (In-Memory Broker)")
        else:
            print("\n--- Phase 2: Process Events ---")

        process_time = await benchmark.run_processing_workers(num_events)
        process_rate = num_events / process_time

        stats = await benchmark.get_stats()

        total_time = insert_time + process_time
        overall_rate = num_events / total_time

        if RICH_AVAILABLE:
            console.print()
            results = Table(title="Benchmark Results", border_style="green")
            results.add_column("Metric", style="cyan")
            results.add_column("Value", justify="right", style="bold")

            results.add_row("Total Events", f"{num_events:,}")
            results.add_row("Workers", str(num_workers))
            results.add_row("Batch Size", str(batch_size))
            results.add_row("─" * 20, "─" * 15)
            results.add_row("Insert Time", f"{insert_time:.2f}s")
            results.add_row("Insert Rate", f"{insert_rate:,.0f}/sec")
            results.add_row("─" * 20, "─" * 15)
            results.add_row("Process Time", f"{process_time:.2f}s")
            results.add_row("Process Rate", f"[bold green]{process_rate:,.0f}/sec[/bold green]")
            results.add_row("─" * 20, "─" * 15)
            results.add_row("Total Time", f"{total_time:.2f}s")
            results.add_row("Overall Rate", f"{overall_rate:,.0f}/sec")
            results.add_row("─" * 20, "─" * 15)
            results.add_row("Events Sent", f"{stats['sent']:,}")
            results.add_row("Events Pending", f"{stats['pending']:,}")

            console.print(results)

            if process_rate >= 5000:
                console.print("\n[bold green]🚀 EXCELLENT![/bold green] High-throughput achieved!")
            elif process_rate >= 2000:
                console.print(
                    "\n[bold yellow]✓ GOOD[/bold yellow] - Solid throughput for local testing"
                )
            elif process_rate >= 500:
                console.print("\n[yellow]⚠ MODERATE[/yellow] - Consider more workers or resources")
            else:
                console.print("\n[red]✗ LOW[/red] - Check system resources")

            time_to_1m = 1_000_000 / process_rate
            console.print(
                f"\n[dim]Time to process 1M events at this rate: {time_to_1m:.1f}s ({time_to_1m / 60:.1f} min)[/dim]"
            )

        else:
            print("\n=== Results ===")
            print(f"Insert: {insert_time:.2f}s ({insert_rate:,.0f}/sec)")
            print(f"Process: {process_time:.2f}s ({process_rate:,.0f}/sec)")
            print(f"Total: {total_time:.2f}s ({overall_rate:,.0f}/sec)")
            print(f"Time to 1M: {1_000_000 / process_rate:.1f}s")

        return {
            "events": num_events,
            "insert_time": insert_time,
            "insert_rate": insert_rate,
            "process_time": process_time,
            "process_rate": process_rate,
            "total_time": total_time,
            "overall_rate": overall_rate,
        }

    finally:
        await benchmark.close()


async def _run(num_events: int, num_workers: int, batch_size: int, db_url: str):
    """Run benchmark (async entry point)."""
    await run_benchmark(
        num_events=num_events,
        num_workers=num_workers,
        batch_size=batch_size,
        db_url=db_url,
    )


def main():
    """Main entry point for sagaz demo run high_throughput."""
    parser = argparse.ArgumentParser(
        description="High-Throughput Benchmark for Sagaz Outbox Pattern"
    )

    parser.add_argument(
        "--events",
        "-e",
        type=int,
        default=100000,
        help="Number of events to process (default: 100000)",
    )

    parser.add_argument(
        "--workers", "-w", type=int, default=20, help="Number of parallel workers (default: 20)"
    )

    parser.add_argument(
        "--batch", "-b", type=int, default=1000, help="Batch size per worker (default: 1000)"
    )

    parser.add_argument("--db-url", default=DATABASE_URL, help="PostgreSQL connection URL")

    args = parser.parse_args()

    asyncio.run(
        _run(
            num_events=args.events,
            num_workers=args.workers,
            batch_size=args.batch,
            db_url=args.db_url,
        )
    )


if __name__ == "__main__":
    main()
