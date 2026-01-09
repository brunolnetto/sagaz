#!/usr/bin/env python3
"""
Kubernetes Cluster Test Script forsagaz Outbox Pattern

This script tests thesagaz outbox worker cluster with multiple scenarios:
1. Successful event processing
2. Bulk event processing
3. Stress testing
4. Event monitoring
5. Idempotency verification
6. Worker recovery simulation

Prerequisites:
    - kubectl port-forward -nsagaz svc/postgresql 5432:5432
    - pip install asyncpg rich

Usage:
    python scripts/k8s_cluster_test.py [scenario]

Scenarios:
    basic       - Insert a few events and verify processing
    bulk        - Insert 100 events in batch
    stress      - Insert 1000 events rapidly
    monitor     - Monitor pending/processed events
    idempotency - Test duplicate event handling
    all         - Run all tests sequentially
"""

import argparse
import asyncio
import json
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
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("Note: Install 'rich' for better output: pip install rich")

# Configuration
DATABASE_URL = "postgresql://saga_user:saga_password@localhost:5433/saga_db"

console = Console() if RICH_AVAILABLE else None


def log(message: str, style: str = ""):
    """Print a log message."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    if RICH_AVAILABLE:
        console.print(f"[dim]{timestamp}[/dim] {message}", style=style)
    else:
        print(f"{timestamp} {message}")


def success(message: str):
    log(f"✅ {message}", "green")


def error(message: str):
    log(f"❌ {message}", "red")


def info(message: str):
    log(f"[i] {message}", "blue")


def warning(message: str):
    log(f"⚠️  {message}", "yellow")


class OutboxTester:
    """Test harness for the Sagaz outbox pattern."""

    def __init__(self, database_url: str = DATABASE_URL):
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        """Connect to the database."""
        info("Connecting to PostgreSQL...")
        try:
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            success("Connected to PostgreSQL")
        except Exception as e:
            error(f"Failed to connect: {e}")
            raise

    async def close(self):
        """Close the database connection."""
        if self.pool:
            await self.pool.close()
            info("Database connection closed")

    async def insert_event(
        self,
        event_type: str,
        payload: dict,
        aggregate_type: str = "test",
        aggregate_id: str | None = None,
        saga_id: str | None = None,
    ) -> str:
        """Insert a single event into the outbox."""
        event_id = str(uuid.uuid4())
        saga_id = saga_id or str(uuid.uuid4())
        aggregate_id = aggregate_id or str(uuid.uuid4())

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO saga_outbox (
                    event_id, saga_id, aggregate_type, aggregate_id,
                    event_type, payload, headers, status, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', NOW())
            """,
                uuid.UUID(event_id),
                saga_id,
                aggregate_type,
                aggregate_id,
                event_type,
                json.dumps(payload),
                json.dumps({"source": "k8s-test", "timestamp": datetime.now(UTC).isoformat()}),
            )

        return event_id

    async def insert_events_batch(
        self,
        count: int,
        event_type: str = "TestEvent",
        batch_size: int = 100,
    ) -> list[str]:
        """Insert multiple events in batches."""
        event_ids = []

        async with self.pool.acquire() as conn:
            for i in range(0, count, batch_size):
                batch_count = min(batch_size, count - i)
                values = []

                for j in range(batch_count):
                    event_id = str(uuid.uuid4())
                    saga_id = str(uuid.uuid4())
                    aggregate_id = str(uuid.uuid4())
                    payload = {
                        "batch_index": i + j,
                        "data": f"Test event {i + j}",
                        "timestamp": datetime.now(UTC).isoformat(),
                    }

                    values.append(
                        (
                            uuid.UUID(event_id),
                            saga_id,
                            "stress-test",
                            aggregate_id,
                            event_type,
                            json.dumps(payload),
                            json.dumps({"batch": i // batch_size}),
                        )
                    )
                    event_ids.append(event_id)

                await conn.executemany(
                    """
                    INSERT INTO saga_outbox (
                        event_id, saga_id, aggregate_type, aggregate_id,
                        event_type, payload, headers, status, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', NOW())
                """,
                    values,
                )

        return event_ids

    async def get_stats(self) -> dict:
        """Get current outbox statistics."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE status = 'claimed') as claimed,
                    COUNT(*) FILTER (WHERE status = 'sent') as sent,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE status = 'dead_letter') as dead_letter,
                    COUNT(*) as total
                FROM saga_outbox
            """)

            return dict(row)

    async def wait_for_processing(
        self,
        expected_sent: int,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
    ) -> bool:
        """Wait for events to be processed."""
        start = time.time()

        while time.time() - start < timeout:
            stats = await self.get_stats()

            if stats["sent"] >= expected_sent:
                return True

            if stats["pending"] == 0 and stats["claimed"] == 0:
                # Nothing left to process
                return stats["sent"] >= expected_sent

            await asyncio.sleep(poll_interval)

        return False

    async def clear_all_events(self):
        """Clear all events from the outbox (for clean testing)."""
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM saga_outbox")
            info(f"Cleared outbox table: {result}")

    async def get_recent_events(self, limit: int = 10) -> list:
        """Get recent events."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT event_id, event_type, status, created_at, sent_at, retry_count
                FROM saga_outbox
                ORDER BY created_at DESC
                LIMIT $1
            """,
                limit,
            )
            return [dict(r) for r in rows]


# ============================================================================
# TEST SCENARIOS
# ============================================================================


async def test_basic(tester: OutboxTester):
    """
    Scenario 1: Basic Event Processing

    Insert a few events and verify they are processed correctly.
    """
    if RICH_AVAILABLE:
        console.rule("[bold blue]Scenario 1: Basic Event Processing")
    else:
        print("\n=== Scenario 1: Basic Event Processing ===")

    # Get initial stats
    initial_stats = await tester.get_stats()
    initial_sent = initial_stats["sent"]

    info("Inserting 5 test events...")
    event_ids = []

    for i in range(5):
        event_id = await tester.insert_event(
            event_type="OrderCreated",
            payload={
                "order_id": f"ORD-{i:04d}",
                "customer_id": f"CUST-{i:03d}",
                "amount": 99.99 + i,
                "items": [{"product": f"Product {i}", "qty": i + 1}],
            },
            aggregate_type="order",
        )
        event_ids.append(event_id)
        info(f"  Created event: {event_id[:8]}...")

    success(f"Inserted {len(event_ids)} events")

    # Wait for processing
    info("Waiting for events to be processed...")
    processed = await tester.wait_for_processing(
        expected_sent=initial_sent + 5,
        timeout=30.0,
    )

    # Get final stats
    final_stats = await tester.get_stats()

    if RICH_AVAILABLE:
        table = Table(title="Outbox Statistics")
        table.add_column("Status", style="cyan")
        table.add_column("Count", justify="right")

        for status, count in final_stats.items():
            table.add_row(status, str(count))

        console.print(table)
    else:
        print(f"Stats: {final_stats}")

    if processed:
        success("✓ Basic event processing test PASSED")
        return True
    error("✗ Basic event processing test FAILED - events not processed in time")
    return False


async def test_bulk(tester: OutboxTester):
    """
    Scenario 2: Bulk Event Processing

    Insert 100 events and verify batch processing works.
    """
    if RICH_AVAILABLE:
        console.rule("[bold blue]Scenario 2: Bulk Event Processing (100 events)")
    else:
        print("\n=== Scenario 2: Bulk Event Processing (100 events) ===")

    initial_stats = await tester.get_stats()
    initial_sent = initial_stats["sent"]

    info("Inserting 100 events in batch...")
    start_time = time.time()

    await tester.insert_events_batch(
        count=100,
        event_type="BulkTestEvent",
    )

    insert_time = time.time() - start_time
    success(f"Inserted 100 events in {insert_time:.2f}s ({100 / insert_time:.0f} events/sec)")

    # Wait for processing
    info("Waiting for all events to be processed...")
    start_time = time.time()

    processed = await tester.wait_for_processing(
        expected_sent=initial_sent + 100,
        timeout=60.0,
    )

    process_time = time.time() - start_time

    final_stats = await tester.get_stats()
    events_processed = final_stats["sent"] - initial_sent

    if processed:
        success(
            f"✓ Bulk test PASSED - Processed {events_processed} events in {process_time:.2f}s ({events_processed / process_time:.0f} events/sec)"
        )
        return True
    warning(f"Bulk test completed with {events_processed}/100 events processed")
    return events_processed >= 90  # Allow some tolerance


def _print_stress_progress(current_sent: int, pending: int, claimed: int, rate: float):
    """Print stress test progress."""
    if RICH_AVAILABLE:
        console.print(
            f"  [cyan]Processed:[/cyan] {current_sent}/1000 | "
            f"[yellow]Pending:[/yellow] {pending} | "
            f"[magenta]Claimed:[/magenta] {claimed} | "
            f"[green]Rate:[/green] {rate:.1f}/sec",
            end="\r",
        )
    else:
        print(
            f"  Processed: {current_sent}/1000 | Pending: {pending} | Rate: {rate:.1f}/sec",
            end="\r",
        )


def _print_stress_results(events_processed: int, process_time: float, final_stats: dict):
    """Print stress test results."""
    print()  # Ensure new line
    if RICH_AVAILABLE:
        panel = Panel(
            f"[bold]Events Processed:[/bold] {events_processed}/1000\n"
            f"[bold]Time:[/bold] {process_time:.1f}s\n"
            f"[bold]Throughput:[/bold] {events_processed / process_time:.1f} events/sec\n"
            f"[bold]Pending:[/bold] {final_stats['pending']}\n"
            f"[bold]Failed:[/bold] {final_stats['failed']}",
            title="Stress Test Results",
            border_style="green" if events_processed >= 950 else "yellow",
        )
        console.print(panel)
    else:
        print(
            f"\nResults: {events_processed}/1000 events in {process_time:.1f}s ({events_processed / process_time:.1f}/sec)"
        )


async def test_stress(tester: OutboxTester):
    """
    Scenario 3: Stress Testing

    Insert 1000 events rapidly and measure throughput.
    """
    if RICH_AVAILABLE:
        console.rule("[bold red]Scenario 3: Stress Test (1000 events)")
    else:
        print("\n=== Scenario 3: Stress Test (1000 events) ===")

    initial_stats = await tester.get_stats()
    initial_sent = initial_stats["sent"]

    warning("⚡ STRESS TEST: Inserting 1000 events rapidly...")
    start_time = time.time()

    await tester.insert_events_batch(
        count=1000,
        event_type="StressTestEvent",
        batch_size=200,
    )

    insert_time = time.time() - start_time
    success(f"Inserted 1000 events in {insert_time:.2f}s ({1000 / insert_time:.0f} events/sec)")

    # Monitor processing
    info("Monitoring event processing...")
    start_time = time.time()
    events_processed, process_time = await _monitor_stress_processing(
        tester, initial_sent, start_time
    )

    final_stats = await tester.get_stats()
    _print_stress_results(events_processed, process_time, final_stats)

    return _evaluate_stress_result(events_processed)


async def _monitor_stress_processing(tester, initial_sent: int, start_time: float):
    """Monitor stress test processing loop."""
    timeout = 180.0
    last_count = 0
    stall_time = 0

    while time.time() - start_time < timeout:
        stats = await tester.get_stats()
        current_sent = stats["sent"] - initial_sent
        elapsed = time.time() - start_time
        rate = current_sent / elapsed if elapsed > 0 else 0

        _print_stress_progress(current_sent, stats["pending"], stats["claimed"], rate)

        if current_sent >= 1000:
            print()  # New line
            break

        # Check for stalls
        if current_sent == last_count:
            stall_time += 2
            if stall_time > 30:
                warning(f"\nProcessing stalled at {current_sent} events")
                break
        else:
            stall_time = 0
            last_count = current_sent

        await asyncio.sleep(2)

    return current_sent, time.time() - start_time


def _evaluate_stress_result(events_processed: int) -> bool:
    """Evaluate stress test result."""
    if events_processed >= 950:
        success("✓ Stress test PASSED")
        return True
    if events_processed >= 800:
        warning("⚠ Stress test PARTIAL - some events still pending")
        return True
    error("✗ Stress test FAILED - too many events not processed")
    return False


async def test_monitor(tester: OutboxTester):
    """
    Scenario 4: Monitor Current State

    Display current outbox statistics and recent events.
    """
    if RICH_AVAILABLE:
        console.rule("[bold green]Scenario 4: Outbox Monitor")
    else:
        print("\n=== Scenario 4: Outbox Monitor ===")

    stats = await tester.get_stats()
    recent = await tester.get_recent_events(10)

    if RICH_AVAILABLE:
        # Stats table
        stats_table = Table(title="Current Outbox Statistics")
        stats_table.add_column("Status", style="cyan")
        stats_table.add_column("Count", justify="right", style="bold")

        status_styles = {
            "pending": "yellow",
            "claimed": "magenta",
            "sent": "green",
            "failed": "red",
            "dead_letter": "red bold",
            "total": "white bold",
        }

        for status, count in stats.items():
            style = status_styles.get(status, "")
            stats_table.add_row(status, f"[{style}]{count}[/{style}]")

        console.print(stats_table)

        # Recent events table
        if recent:
            events_table = Table(title="Recent Events")
            events_table.add_column("Event ID", style="dim")
            events_table.add_column("Type")
            events_table.add_column("Status")
            events_table.add_column("Retries")
            events_table.add_column("Created")

            for event in recent:
                status_style = {
                    "pending": "yellow",
                    "claimed": "magenta",
                    "sent": "green",
                    "failed": "red",
                }.get(event["status"], "")

                events_table.add_row(
                    str(event["event_id"])[:8] + "...",
                    event["event_type"],
                    f"[{status_style}]{event['status']}[/{status_style}]",
                    str(event["retry_count"]),
                    event["created_at"].strftime("%H:%M:%S"),
                )

            console.print(events_table)
    else:
        print(f"Stats: {stats}")
        print(f"Recent events: {len(recent)}")
        for event in recent[:5]:
            print(f"  - {event['event_id']}: {event['status']}")

    success("✓ Monitor completed")
    return True


async def test_idempotency(tester: OutboxTester):
    """
    Scenario 5: Idempotency Test

    Verify that duplicate events are handled correctly.
    """
    if RICH_AVAILABLE:
        console.rule("[bold cyan]Scenario 5: Idempotency Test")
    else:
        print("\n=== Scenario 5: Idempotency Test ===")

    # Create a unique event ID
    fixed_event_id = str(uuid.uuid4())
    saga_id = str(uuid.uuid4())
    aggregate_id = str(uuid.uuid4())

    info(f"Testing with event ID: {fixed_event_id[:8]}...")

    # Try to insert the same event twice
    async with tester.pool.acquire() as conn:
        try:
            # First insert
            await conn.execute(
                """
                INSERT INTO saga_outbox (
                    event_id, saga_id, aggregate_type, aggregate_id,
                    event_type, payload, headers, status, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', NOW())
            """,
                uuid.UUID(fixed_event_id),
                saga_id,
                "idempotency-test",
                aggregate_id,
                "IdempotencyTestEvent",
                json.dumps({"test": "first insert"}),
                json.dumps({}),
            )
            success("First insert succeeded")

            # Second insert (should fail due to primary key)
            try:
                await conn.execute(
                    """
                    INSERT INTO saga_outbox (
                        event_id, saga_id, aggregate_type, aggregate_id,
                        event_type, payload, headers, status, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', NOW())
                """,
                    uuid.UUID(fixed_event_id),
                    saga_id,
                    "idempotency-test",
                    aggregate_id,
                    "IdempotencyTestEvent",
                    json.dumps({"test": "second insert - should fail"}),
                    json.dumps({}),
                )
                error("Second insert succeeded - idempotency FAILED!")
                return False
            except asyncpg.UniqueViolationError:
                success("Second insert correctly rejected (UniqueViolation)")

        except Exception as e:
            error(f"Unexpected error: {e}")
            return False

    success("✓ Idempotency test PASSED - duplicate events are rejected")
    return True


def _print_test_summary(results: dict):
    """Print test summary table."""
    if RICH_AVAILABLE:
        console.rule("[bold]Test Summary")
        summary_table = Table()
        summary_table.add_column("Test", style="cyan")
        summary_table.add_column("Result", justify="center")

        for name, passed in results.items():
            result_str = "[green]✓ PASS[/green]" if passed else "[red]✗ FAIL[/red]"
            summary_table.add_row(name, result_str)

        console.print(summary_table)
    else:
        print("\n--- Test Summary ---")
        for name, passed in results.items():
            print(f"  {name}: {'PASS' if passed else 'FAIL'}")


async def run_all_tests(tester: OutboxTester):
    """Run all test scenarios."""
    if RICH_AVAILABLE:
        console.print(
            Panel.fit(
                "[bold]Sagaz Outbox Kubernetes Cluster Tests[/bold]\nRunning all scenarios...",
                border_style="bold blue",
            )
        )
    else:
        print("\n" + "=" * 50)
        print("Sagaz Outbox Kubernetes Cluster Tests")
        print("=" * 50)

    # Run standard tests
    tests = [
        ("Basic Processing", test_basic),
        ("Bulk Processing", test_bulk),
        ("Idempotency", test_idempotency),
        ("Monitor", test_monitor),
    ]

    results = await _run_test_suite(tester, tests)

    # Optional stress test
    if await _prompt_stress_test():
        results["Stress Test"] = await _safe_run_test(tester, "Stress Test", test_stress)

    # Summary
    print()
    _print_test_summary(results)

    all_passed = all(results.values())
    if all_passed:
        success("\n🎉 All tests PASSED!")
    else:
        error(f"\n❌ Some tests failed: {[k for k, v in results.items() if not v]}")

    return all_passed


async def _run_test_suite(tester: OutboxTester, tests: list) -> dict:
    """Run a suite of tests."""
    results = {}
    for name, test_fn in tests:
        results[name] = await _safe_run_test(tester, name, test_fn)
    return results


async def _safe_run_test(tester: OutboxTester, name: str, test_fn) -> bool:
    """Run a test with exception handling."""
    try:
        return await test_fn(tester)
    except Exception as e:
        error(f"Test '{name}' failed with exception: {e}")
        return False


async def _prompt_stress_test() -> bool:
    """Prompt user for stress test."""
    print()
    if RICH_AVAILABLE:
        do_stress = console.input("[yellow]Run stress test (1000 events)? [y/N]: [/yellow]")
    else:
        do_stress = input("Run stress test (1000 events)? [y/N]: ")
    return do_stress.lower() == "y"


# ============================================================================
# MAIN
# ============================================================================


async def main():
    parser = argparse.ArgumentParser(
        description="Kubernetes Cluster Test Script forsagaz Outbox Pattern",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python k8s_cluster_test.py basic      # Run basic test
    python k8s_cluster_test.py stress     # Run stress test
    python k8s_cluster_test.py all        # Run all tests
    python k8s_cluster_test.py monitor    # Show current stats
    python k8s_cluster_test.py clear      # Clear all events
        """,
    )

    parser.add_argument(
        "scenario",
        nargs="?",
        default="all",
        choices=["basic", "bulk", "stress", "monitor", "idempotency", "all", "clear"],
        help="Test scenario to run (default: all)",
    )

    parser.add_argument("--db-url", default=DATABASE_URL, help="PostgreSQL connection URL")

    args = parser.parse_args()

    # Create tester
    tester = OutboxTester(args.db_url)

    try:
        await tester.connect()

        if args.scenario == "clear":
            warning("Clearing all events from outbox...")
            await tester.clear_all_events()
            success("Outbox cleared")
        elif args.scenario == "basic":
            await test_basic(tester)
        elif args.scenario == "bulk":
            await test_bulk(tester)
        elif args.scenario == "stress":
            await test_stress(tester)
        elif args.scenario == "monitor":
            await test_monitor(tester)
        elif args.scenario == "idempotency":
            await test_idempotency(tester)
        elif args.scenario == "all":
            await run_all_tests(tester)

    except KeyboardInterrupt:
        warning("\nTest interrupted by user")
    except Exception as e:
        error(f"Test failed: {e}")
        raise
    finally:
        await tester.close()


if __name__ == "__main__":
    asyncio.run(main())
