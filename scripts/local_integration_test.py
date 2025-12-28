#!/usr/bin/env python3
"""
Local Integration Test Script for Sagaz

This script performs a comprehensive local integration test covering:
1. Saga execution with state persistence
2. PostgreSQL storage backend
3. Redis broker for outbox events
4. Outbox worker processing
5. Prometheus metrics exposure

Prerequisites:
    - Docker running
    - Run `sagaz init --local` first, then `sagaz dev` to start services
    - OR run from /tmp/sagaz-test after init

Usage:
    cd /tmp/sagaz-test  # or wherever you ran sagaz init
    python /path/to/local_integration_test.py

    # Or with the sagaz venv activated:
    python scripts/local_integration_test.py
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.integration_test")

# Test results tracking
test_results: dict[str, dict[str, Any]] = {}


def record_result(test_name: str, success: bool, message: str = "", details: Any = None):
    """Record a test result."""
    test_results[test_name] = {
        "success": success,
        "message": message,
        "details": details,
        "timestamp": datetime.now().isoformat()
    }
    status = "✅ PASS" if success else "❌ FAIL"
    logger.info(f"{status}: {test_name} - {message}")


# ============================================================================
# TEST 1: Basic Saga Execution (Classic/Imperative API)
# ============================================================================

async def test_basic_saga_execution():
    """Test basic saga execution using the ClassicSaga API."""
    test_name = "Basic Saga Execution (ClassicSaga)"
    
    try:
        from sagaz import ClassicSaga, SagaContext
        
        # Create a simple saga using the ClassicSaga imperative API
        saga = ClassicSaga(name="TestOrderSaga", version="1.0")
        
        execution_log = []
        
        async def validate_order(ctx: SagaContext):
            execution_log.append("validate_order")
            return {"validated": True, "order_id": "ORD-TEST-001"}
        
        async def reserve_inventory(ctx: SagaContext):
            execution_log.append("reserve_inventory")
            return {"reserved": True, "items": 3}
        
        async def process_payment(ctx: SagaContext):
            execution_log.append("process_payment")
            return {"payment_id": "PAY-001", "amount": 99.99}
        
        # Add steps
        await saga.add_step(name="validate_order", action=validate_order)
        await saga.add_step(name="reserve_inventory", action=reserve_inventory)
        await saga.add_step(name="process_payment", action=process_payment)
        
        # Execute saga
        result = await saga.execute()
        
        if result.success and len(execution_log) == 3:
            record_result(
                test_name, 
                True, 
                f"Saga completed successfully with {len(execution_log)} steps",
                {"execution_log": execution_log, "status": result.status.value}
            )
        else:
            record_result(
                test_name,
                False,
                f"Saga execution incomplete: {result.error}",
                {"execution_log": execution_log}
            )
            
    except Exception as e:
        record_result(test_name, False, f"Exception: {e}")


# ============================================================================
# TEST 2: Declarative Saga with Compensation
# ============================================================================

async def test_declarative_saga_compensation():
    """Test declarative saga with compensation on failure."""
    test_name = "Declarative Saga Compensation"
    
    try:
        from sagaz import Saga, action, compensate, SagaStepError
        
        compensation_log = []
        
        class TestCompensationSaga(Saga):
            saga_name = "compensation-test"
            
            @action("step_1")
            async def step_1(self, ctx):
                return {"step": 1}
            
            @compensate("step_1")
            async def comp_step_1(self, ctx):
                compensation_log.append("compensated_step_1")
            
            @action("step_2", depends_on=["step_1"])
            async def step_2(self, ctx):
                return {"step": 2}
            
            @compensate("step_2")
            async def comp_step_2(self, ctx):
                compensation_log.append("compensated_step_2")
            
            @action("failing_step", depends_on=["step_2"])
            async def failing_step(self, ctx):
                raise SagaStepError("Intentional failure for testing")
        
        saga = TestCompensationSaga()
        
        try:
            await saga.run({})
        except SagaStepError:
            pass  # Expected failure
        
        # Should have rolled back steps 2 and 1 (in reverse order)
        if len(compensation_log) == 2:
            record_result(
                test_name,
                True,
                f"Compensation executed correctly with {len(compensation_log)} compensations",
                {"compensation_log": compensation_log}
            )
        else:
            record_result(
                test_name,
                False,
                f"Expected 2 compensations, got {len(compensation_log)}",
                {"compensation_log": compensation_log}
            )
            
    except Exception as e:
        record_result(test_name, False, f"Exception: {e}")


# ============================================================================
# TEST 3: PostgreSQL Outbox Storage
# ============================================================================

async def test_postgresql_outbox_storage():
    """Test PostgreSQL storage for outbox events."""
    test_name = "PostgreSQL Outbox Storage"
    
    try:
        from sagaz.outbox.storage.postgresql import ASYNCPG_AVAILABLE
        
        if not ASYNCPG_AVAILABLE:
            record_result(test_name, False, "asyncpg not installed - skipping")
            return
        
        from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage
        from sagaz.outbox.types import OutboxEvent
        
        # Connect to local PostgreSQL (from docker-compose)
        storage = PostgreSQLOutboxStorage(
            connection_string="postgresql://postgres:postgres@localhost:5433/sagaz"
        )
        
        try:
            await storage.initialize()
            
            # Create a test outbox event
            event = OutboxEvent(
                saga_id=f"test-saga-{int(time.time())}",
                event_type="order.created",
                payload={"order_id": "ORD-INT-001", "amount": 99.99}
            )
            
            # Insert the event
            await storage.insert(event)
            
            # Retrieve the event
            retrieved = await storage.get_by_id(event.event_id)
            
            if retrieved and retrieved.saga_id == event.saga_id:
                record_result(
                    test_name,
                    True,
                    f"Successfully stored and retrieved outbox event",
                    {"event_id": event.event_id}
                )
            else:
                record_result(test_name, False, "Failed to retrieve outbox event")
                
        finally:
            # PostgreSQLOutboxStorage uses connection pool, close it properly
            if hasattr(storage, '_pool') and storage._pool:
                await storage._pool.close()
            
    except Exception as e:
        record_result(test_name, False, f"Exception (is PostgreSQL running?): {e}")


# ============================================================================
# TEST 4: Redis Broker
# ============================================================================

async def test_redis_broker():
    """Test Redis broker for publishing outbox events."""
    test_name = "Redis Broker"
    
    try:
        from sagaz.outbox.brokers.redis import REDIS_AVAILABLE
        
        if not REDIS_AVAILABLE:
            record_result(test_name, False, "redis not installed - skipping")
            return
        
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig
        
        config = RedisBrokerConfig(
            url="redis://localhost:6379/0",
            stream_name="sagaz_integration_test"  # NOT stream_prefix
        )
        
        broker = RedisBroker(config)
        
        try:
            await broker.connect()
            
            # Health check
            healthy = await broker.health_check()
            if not healthy:
                record_result(test_name, False, "Broker health check failed")
                return
            
            # Publish a test message
            test_topic = "integration.test"
            test_message = json.dumps({"event": "test", "timestamp": time.time()}).encode()
            
            await broker.publish(
                topic=test_topic,
                message=test_message,
                headers={"trace_id": "test-trace-001"}
            )
            
            record_result(
                test_name,
                True,
                "Successfully connected and published to Redis",
                {"stream": config.stream_name}
            )
            
        finally:
            await broker.close()
            
    except Exception as e:
        record_result(test_name, False, f"Exception (is Redis running?): {e}")


# ============================================================================
# TEST 5: Outbox Pattern End-to-End
# ============================================================================

async def test_outbox_pattern():
    """Test the complete outbox pattern flow."""
    test_name = "Outbox Pattern E2E"
    
    try:
        from sagaz.outbox.storage.postgresql import ASYNCPG_AVAILABLE
        from sagaz.outbox.brokers.redis import REDIS_AVAILABLE
        
        if not ASYNCPG_AVAILABLE:
            record_result(test_name, False, "asyncpg not installed - skipping")
            return
        
        if not REDIS_AVAILABLE:
            record_result(test_name, False, "redis not installed - skipping")
            return
        
        from sagaz.outbox.storage.postgresql import PostgreSQLOutboxStorage
        from sagaz.outbox.brokers.redis import RedisBroker, RedisBrokerConfig
        from sagaz.outbox.types import OutboxEvent, OutboxConfig
        from sagaz.outbox.worker import OutboxWorker
        
        # Setup storage
        storage = PostgreSQLOutboxStorage(
            connection_string="postgresql://postgres:postgres@localhost:5433/sagaz"
        )
        
        # Setup broker
        broker_config = RedisBrokerConfig(
            url="redis://localhost:6379/0",
            stream_name="sagaz_outbox_e2e"
        )
        broker = RedisBroker(broker_config)
        
        try:
            await storage.initialize()
            await broker.connect()
            
            # Step 1: Insert an event into the outbox
            event = OutboxEvent(
                saga_id=f"outbox-test-{int(time.time())}",
                event_type="order.created",
                payload={"order_id": "ORD-E2E-001", "amount": 149.99}
            )
            await storage.insert(event)
            
            # Step 2: Verify event is pending
            pending_count = await storage.get_pending_count()
            if pending_count < 1:
                record_result(test_name, False, "Event not found in outbox")
                return
            
            # Step 3: Create worker and process
            config = OutboxConfig(batch_size=10)
            worker = OutboxWorker(
                storage=storage,
                broker=broker,
                config=config,
                worker_id="integration-test-worker"
            )
            
            processed = await worker.process_batch()
            
            # Step 4: Verify event was processed
            pending_after = await storage.get_pending_count()
            
            if processed >= 1 and pending_after < pending_count:
                record_result(
                    test_name,
                    True,
                    f"Processed {processed} events via outbox pattern",
                    {
                        "pending_before": pending_count,
                        "pending_after": pending_after,
                        "event_id": event.event_id
                    }
                )
            else:
                record_result(
                    test_name,
                    False,
                    f"Processing incomplete: processed={processed}"
                )
                
        finally:
            await broker.close()
            if hasattr(storage, '_pool') and storage._pool:
                await storage._pool.close()
            
    except Exception as e:
        record_result(test_name, False, f"Exception: {e}")


# ============================================================================
# TEST 6: Prometheus Metrics
# ============================================================================

async def test_prometheus_metrics():
    """Test Prometheus metrics endpoint."""
    test_name = "Prometheus Metrics"
    
    try:
        import urllib.request
        
        with urllib.request.urlopen("http://localhost:9090/api/v1/status/runtimeinfo", timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                record_result(
                    test_name,
                    True,
                    "Prometheus is running and accessible",
                    {"status": data.get("status")}
                )
            else:
                record_result(test_name, False, f"Prometheus returned status {response.status}")
    except Exception as e:
        record_result(test_name, False, f"Cannot reach Prometheus: {e}")


# ============================================================================
# TEST 7: Grafana Dashboard
# ============================================================================

async def test_grafana_dashboard():
    """Test Grafana dashboard is accessible."""
    test_name = "Grafana Dashboard"
    
    try:
        import urllib.request
        
        # Give Grafana more time to start up
        await asyncio.sleep(2)
        
        # Grafana health endpoint
        with urllib.request.urlopen("http://localhost:3000/api/health", timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                record_result(
                    test_name,
                    True,
                    "Grafana is running and accessible",
                    {"database": data.get("database")}
                )
            else:
                record_result(test_name, False, f"Grafana returned status {response.status}")
                
    except Exception as e:
        record_result(test_name, False, f"Cannot reach Grafana: {e}")


# ============================================================================
# TEST 8: Saga Listeners
# ============================================================================

async def test_saga_listeners():
    """Test saga with listeners for observability."""
    test_name = "Saga Listeners"
    
    try:
        from sagaz import Saga, action, LoggingSagaListener
        
        # Track listener calls
        listener_calls = []
        
        class TrackingListener:
            """Simple listener that tracks calls."""
            
            def on_saga_start(self, saga_name, saga_id, context):
                listener_calls.append(f"start:{saga_name}")
            
            def on_step_enter(self, saga_name, step_name, context):
                listener_calls.append(f"enter:{step_name}")
            
            def on_step_success(self, saga_name, step_name, context, result):
                listener_calls.append(f"success:{step_name}")
            
            def on_saga_complete(self, saga_name, saga_id, context):
                listener_calls.append(f"complete:{saga_name}")
        
        class TrackedSaga(Saga):
            saga_name = "tracked-saga"
            listeners = [TrackingListener()]
            
            @action("tracked_step")
            async def tracked_step(self, ctx):
                return {"tracked": True}
        
        saga = TrackedSaga()
        await saga.run({})
        
        expected_calls = ["start:tracked-saga", "enter:tracked_step", "success:tracked_step", "complete:tracked-saga"]
        
        if listener_calls == expected_calls:
            record_result(
                test_name,
                True,
                "Listeners received all expected events",
                {"calls": listener_calls}
            )
        else:
            record_result(
                test_name,
                False,
                f"Listener calls mismatch",
                {"expected": expected_calls, "actual": listener_calls}
            )
            
    except Exception as e:
        record_result(test_name, False, f"Exception: {e}")


# ============================================================================
# MAIN RUNNER
# ============================================================================

async def run_all_tests():
    """Run all integration tests."""
    print("\n" + "=" * 70)
    print("🧪 SAGAZ LOCAL INTEGRATION TEST SUITE")
    print("=" * 70)
    print(f"Started at: {datetime.now().isoformat()}")
    print("-" * 70 + "\n")
    
    # Run tests in sequence
    await test_basic_saga_execution()
    await test_declarative_saga_compensation()
    await test_postgresql_outbox_storage()
    await test_redis_broker()
    await test_outbox_pattern()
    await test_prometheus_metrics()
    await test_grafana_dashboard()
    await test_saga_listeners()
    
    # Print summary
    print("\n" + "=" * 70)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for r in test_results.values() if r["success"])
    failed = sum(1 for r in test_results.values() if not r["success"])
    total = len(test_results)
    
    for test_name, result in test_results.items():
        status = "✅" if result["success"] else "❌"
        print(f"  {status} {test_name}: {result['message']}")
    
    print("-" * 70)
    print(f"Total: {total} | Passed: {passed} | Failed: {failed}")
    print(f"Success Rate: {(passed/total)*100:.1f}%" if total > 0 else "N/A")
    print("=" * 70 + "\n")
    
    # Exit with error code if any tests failed
    if failed > 0:
        print("⚠️  Some tests failed. Make sure Docker services are running:")
        print("   1. cd /tmp/sagaz-test  # or wherever you ran sagaz init")
        print("   2. sagaz dev           # starts docker-compose")
        print("   3. Wait for services to be healthy")
        print("   4. Re-run this script")
        sys.exit(1)
    else:
        print("🎉 All tests passed! Sagaz is working correctly.")
        sys.exit(0)


def main():
    """Entry point."""
    asyncio.run(run_all_tests())


if __name__ == "__main__":
    main()
