# Wiring Guide: Adding Flexible Compensation to Existing Outbox Implementation

## Quick Start: 3 Files to Add

```
saga/
├── compensation_graph.py          # NEW: Compensation dependency graph
├── saga_orchestrator.py           # NEW: Integrated orchestrator
├── decorators.py                  # NEW: @step and @compensate decorators
├── storage_postgres.py            # EXISTING (no changes needed)
├── outbox_worker.py               # EXISTING (no changes needed)
├── optimistic_publisher.py        # EXISTING (no changes needed)
└── outbox_statemachine.py         # EXISTING (no changes needed)
```

## File 1: `saga/compensation_graph.py`

```python
"""
Compensation dependency graph management.

Drop-in addition - no changes to existing code needed.
"""
from typing import Dict, List, Callable, Awaitable
from dataclasses import dataclass, field


@dataclass
class CompensationNode:
    """Node in compensation dependency graph."""
    step_id: str
    compensation_fn: Callable[[Dict], Awaitable[None]]
    depends_on: List[str] = field(default_factory=list)
    compensation_type: str = "mechanical"


class SagaCompensationGraph:
    """
    Manages compensation dependencies and execution order.
    
    Usage:
        graph = SagaCompensationGraph()
        graph.register_compensation("step1", undo_step1)
        graph.register_compensation("step2", undo_step2, depends_on=["step1"])
        
        # Execute in dependency order
        levels = graph.get_compensation_order()
        for level in levels:
            await execute_parallel(level)
    """
    
    def __init__(self):
        self.nodes: Dict[str, CompensationNode] = {}
        self.executed_steps: List[str] = []
    
    def register_compensation(
        self,
        step_id: str,
        compensation_fn: Callable,
        depends_on: List[str] = None,
        compensation_type: str = "mechanical"
    ):
        """Register a compensation action for a step."""
        node = CompensationNode(
            step_id=step_id,
            compensation_fn=compensation_fn,
            depends_on=depends_on or [],
            compensation_type=compensation_type
        )
        self.nodes[step_id] = node
    
    def mark_step_executed(self, step_id: str):
        """Mark a step as successfully executed."""
        if step_id not in self.executed_steps:
            self.executed_steps.append(step_id)
    
    def get_compensation_order(self) -> List[List[str]]:
        """
        Compute compensation execution order respecting dependencies.
        
        Returns list of levels, where each level can execute in parallel.
        
        Example:
            [[step_a, step_b], [step_c]]
            # step_a and step_b can run in parallel
            # step_c must wait for both to complete
        """
        to_compensate = [
            step_id for step_id in self.executed_steps 
            if step_id in self.nodes
        ]
        
        if not to_compensate:
            return []
        
        # Build dependency graph
        comp_deps = {}
        for step_id in to_compensate:
            node = self.nodes[step_id]
            valid_deps = [
                dep for dep in node.depends_on 
                if dep in to_compensate
            ]
            comp_deps[step_id] = valid_deps
        
        # Topological sort with levels (Kahn's algorithm)
        levels = []
        in_degree = {step: len(deps) for step, deps in comp_deps.items()}
        
        while any(deg == 0 for deg in in_degree.values()):
            current_level = [
                step for step, deg in in_degree.items() 
                if deg == 0
            ]
            
            if not current_level:
                break
            
            levels.append(current_level)
            
            for step in current_level:
                in_degree[step] = -1
                
                for other_step, deps in comp_deps.items():
                    if step in deps and in_degree[other_step] > 0:
                        in_degree[other_step] -= 1
        
        return levels
```

## File 2: `saga/saga_orchestrator.py`

```python
"""
Saga orchestrator integrating outbox + compensation graph.

Wires together existing components without modifying them.
"""
import asyncio
from typing import Dict, List, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from asyncpg import Pool

from .interfaces import SagaState, SagaStatus, OutboxEvent
from .storage_postgres import PostgresSagaStorage
from .optimistic_publisher import OptimisticPublisher
from .compensation_graph import SagaCompensationGraph


@dataclass
class SagaStepDefinition:
    """Definition of a saga step with compensation."""
    step_id: str
    forward_fn: Callable[[Dict], Awaitable[Optional[Dict]]]
    compensation_fn: Optional[Callable[[Dict], Awaitable[None]]] = None
    depends_on: List[str] = field(default_factory=list)
    compensation_depends_on: List[str] = field(default_factory=list)
    compensation_type: str = "mechanical"
    aggregate_type: Optional[str] = None
    event_type: Optional[str] = None


class IntegratedSagaOrchestrator:
    """
    Saga orchestrator using existing outbox infrastructure.
    
    NEW: Adds flexible compensation graph
    USES: Existing storage, optimistic publisher, outbox worker
    
    Usage:
        orchestrator = IntegratedSagaOrchestrator(storage, optimistic_pub, pool)
        
        steps = [
            SagaStepDefinition("create", create_fn, cancel_fn),
            SagaStepDefinition("charge", charge_fn, refund_fn, depends_on=["create"])
        ]
        
        await orchestrator.execute_saga(saga_id, "OrderSaga", steps, context)
    """
    
    def __init__(
        self,
        storage: PostgresSagaStorage,
        optimistic_publisher: OptimisticPublisher,
        pool: Pool
    ):
        self.storage = storage
        self.optimistic_publisher = optimistic_publisher
        self.pool = pool
        self.compensation_graph = SagaCompensationGraph()
    
    async def execute_saga(
        self,
        saga_id: str,
        saga_type: str,
        steps: List[SagaStepDefinition],
        initial_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute saga with transactional outbox and flexible compensation."""
        
        # Create saga instance using existing storage
        saga = SagaState(
            id=saga_id,
            saga_type=saga_type,
            correlation_id=str(uuid4()),
            state=initial_context.copy(),
            status=SagaStatus.STARTED,
            version=0
        )
        await self.storage.create(saga)
        
        # Build execution graph from dependencies
        exec_graph = self._build_execution_graph(steps)
        
        try:
            # Execute steps level by level (enables parallelization)
            for level in exec_graph:
                await self._execute_level(saga_id, level, saga.state)
                saga = await self.storage.load(saga_id)
            
            # Mark saga as completed using existing storage
            saga = await self.storage.load(saga_id)
            await self.storage.save(
                saga_id,
                saga.state,
                SagaStatus.COMPLETED,
                saga.version
            )
            
            return saga.state
        
        except Exception:
            # Trigger compensation using dependency graph
            await self._compensate_saga(saga_id)
            raise
    
    def _build_execution_graph(
        self, 
        steps: List[SagaStepDefinition]
    ) -> List[List[SagaStepDefinition]]:
        """Build execution levels from step dependencies."""
        step_map = {s.step_id: s for s in steps}
        in_degree = {s.step_id: len(s.depends_on) for s in steps}
        
        levels = []
        remaining = set(step_map.keys())
        
        while remaining:
            current_level = [
                step_map[sid] for sid in remaining
                if in_degree[sid] == 0
            ]
            
            if not current_level:
                raise ValueError("Circular dependency detected")
            
            levels.append(current_level)
            
            for step in current_level:
                remaining.remove(step.step_id)
                for other_id in remaining:
                    if step.step_id in step_map[other_id].depends_on:
                        in_degree[other_id] -= 1
        
        return levels
    
    async def _execute_level(
        self,
        saga_id: str,
        level: List[SagaStepDefinition],
        context: Dict[str, Any]
    ):
        """Execute all steps in a level concurrently."""
        tasks = [
            self._execute_step_with_outbox(saga_id, step, context)
            for step in level
        ]
        await asyncio.gather(*tasks)
    
    async def _execute_step_with_outbox(
        self,
        saga_id: str,
        step: SagaStepDefinition,
        context: Dict[str, Any]
    ):
        """
        Execute step using EXISTING outbox pattern.
        
        CRITICAL: This uses existing storage methods - no new DB code!
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Use existing storage.load with FOR UPDATE
                saga = await self.storage.load(saga_id, for_update=True)
                
                # Idempotency check (existing pattern)
                if saga.state.get(f"{step.step_id}_completed"):
                    return
                
                # Execute business logic
                result = await step.forward_fn(context)
                
                # Update saga state
                saga.state[f"{step.step_id}_completed"] = True
                if result:
                    saga.state.update(result)
                
                # Use existing storage.save with connection
                await self.storage.save(
                    saga_id,
                    saga.state,
                    SagaStatus.RUNNING,
                    saga.version,
                    current_step=step.step_id,
                    conn=conn
                )
                
                # Create outbox event (existing pattern)
                event = OutboxEvent(
                    event_id=str(uuid4()),
                    saga_id=saga_id,
                    aggregate_type=step.aggregate_type or "saga",
                    aggregate_id=saga_id,
                    event_type=step.event_type or f"{step.step_id}_completed",
                    payload={
                        "saga_id": saga_id,
                        "step_id": step.step_id,
                        "result": result,
                        "timestamp": datetime.utcnow().isoformat()
                    },
                    headers={
                        "trace_id": str(uuid4()),
                        "message_id": str(uuid4()),
                        "causation_id": saga_id
                    }
                )
                
                # Use existing storage.append_outbox
                await self.storage.append_outbox(event, conn=conn)
                
                # NEW: Register compensation in graph
                if step.compensation_fn:
                    self.compensation_graph.register_compensation(
                        step.step_id,
                        step.compensation_fn,
                        depends_on=step.compensation_depends_on,
                        compensation_type=step.compensation_type
                    )
                
                self.compensation_graph.mark_step_executed(step.step_id)
            
            # Use existing optimistic publisher (outside transaction)
            await self.optimistic_publisher.publish_after_commit(event)
    
    async def _compensate_saga(self, saga_id: str):
        """Execute compensations using dependency graph."""
        saga = await self.storage.load(saga_id)
        await self.storage.save(
            saga_id,
            saga.state,
            SagaStatus.COMPENSATING,
            saga.version
        )
        
        # NEW: Get compensation order from graph
        comp_levels = self.compensation_graph.get_compensation_order()
        
        # Execute compensations level by level
        for level in comp_levels:
            tasks = [
                self._execute_compensation_with_outbox(saga_id, sid, saga.state)
                for sid in level
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
        
        saga = await self.storage.load(saga_id)
        await self.storage.save(
            saga_id,
            saga.state,
            SagaStatus.FAILED,
            saga.version
        )
    
    async def _execute_compensation_with_outbox(
        self,
        saga_id: str,
        step_id: str,
        context: Dict[str, Any]
    ):
        """Execute compensation using EXISTING outbox pattern."""
        node = self.compensation_graph.nodes[step_id]
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                saga = await self.storage.load(saga_id)
                
                # Idempotency
                if saga.state.get(f"{step_id}_compensated"):
                    return
                
                # Execute compensation
                await node.compensation_fn(context)
                
                # Update state
                saga.state[f"{step_id}_compensated"] = True
                
                await self.storage.save(
                    saga_id,
                    saga.state,
                    SagaStatus.COMPENSATING,
                    saga.version,
                    conn=conn
                )
                
                # Create compensation event (for audit)
                event = OutboxEvent(
                    event_id=str(uuid4()),
                    saga_id=saga_id,
                    aggregate_type="saga",
                    aggregate_id=saga_id,
                    event_type=f"{step_id}_compensated",
                    payload={
                        "saga_id": saga_id,
                        "step_id": step_id,
                        "compensation_type": node.compensation_type,
                        "timestamp": datetime.utcnow().isoformat()
                    },
                    headers={
                        "trace_id": str(uuid4()),
                        "message_id": str(uuid4()),
                        "causation_id": saga_id
                    }
                )
                
                await self.storage.append_outbox(event, conn=conn)
```

## File 3: `saga/decorators.py`

```python
"""
Decorator API for declarative sagas.

Makes saga definition user-friendly without changing existing infrastructure.
"""
from typing import Dict, List, Any, Callable, Awaitable, Optional
from dataclasses import dataclass

from .saga_orchestrator import IntegratedSagaOrchestrator, SagaStepDefinition


def step(name: str, depends_on: List[str] = None, 
         aggregate_type: str = None, event_type: str = None):
    """
    Decorator to mark a method as a saga step.
    
    Usage:
        @step(name="create_order", aggregate_type="order")
        async def create_order(self, ctx):
            return await OrderService.create(ctx)
    """
    def decorator(func):
        func._saga_step_meta = {
            'name': name,
            'depends_on': depends_on or [],
            'aggregate_type': aggregate_type,
            'event_type': event_type
        }
        return func
    return decorator


def compensate(for_step: str, depends_on: List[str] = None, 
               compensation_type: str = "mechanical"):
    """
    Decorator to mark a method as compensation for a step.
    
    Usage:
        @compensate("create_order")
        async def cancel_order(self, ctx):
            await OrderService.delete(ctx["order_id"])
    """
    def decorator(func):
        func._saga_compensation_meta = {
            'for_step': for_step,
            'depends_on': depends_on or [],
            'type': compensation_type
        }
        return func
    return decorator


class DeclarativeSaga:
    """
    Base class for declarative saga definitions.
    
    Usage:
        class OrderSaga(DeclarativeSaga):
            @step(name="create_order")
            async def create_order(self, ctx): ...
            
            @compensate("create_order")
            async def cancel_order(self, ctx): ...
        
        saga = OrderSaga()
        await saga.execute(orchestrator, saga_id, context)
    """
    
    def __init__(self):
        self._steps: List[SagaStepDefinition] = []
        self._step_registry: Dict[str, SagaStepDefinition] = {}
        self._collect_steps()
    
    def _collect_steps(self):
        """Collect decorated methods into step definitions."""
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            
            if hasattr(attr, '_saga_step_meta'):
                meta = attr._saga_step_meta
                step_def = SagaStepDefinition(
                    step_id=meta['name'],
                    forward_fn=attr,
                    depends_on=meta.get('depends_on', []),
                    aggregate_type=meta.get('aggregate_type'),
                    event_type=meta.get('event_type')
                )
                self._steps.append(step_def)
                self._step_registry[meta['name']] = step_def
        
        # Attach compensations
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            
            if hasattr(attr, '_saga_compensation_meta'):
                meta = attr._saga_compensation_meta
                step_name = meta['for_step']
                
                if step_name in self._step_registry:
                    step = self._step_registry[step_name]
                    step.compensation_fn = attr
                    step.compensation_depends_on = meta.get('depends_on', [])
                    step.compensation_type = meta.get('type', 'mechanical')
    
    async def execute(
        self,
        orchestrator: IntegratedSagaOrchestrator,
        saga_id: str,
        initial_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute this saga using the orchestrator."""
        return await orchestrator.execute_saga(
            saga_id=saga_id,
            saga_type=self.__class__.__name__,
            steps=self._steps,
            initial_context=initial_context
        )
```

## Usage Example: `examples/order_saga.py`

```python
"""
Example: Order saga using new decorators with existing infrastructure.
"""
import asyncio
from uuid import uuid4

from asyncpg import create_pool

# Existing imports (no changes)
from saga.storage_postgres import PostgresSagaStorage
from saga.broker_kafka import KafkaBroker
from saga.optimistic_publisher import OptimisticPublisher

# NEW imports
from saga.saga_orchestrator import IntegratedSagaOrchestrator
from saga.decorators import DeclarativeSaga, step, compensate


# Business services (unchanged)
class OrderService:
    @staticmethod
    async def create(data): 
        return {"order_id": "ORD-123"}
    
    @staticmethod
    async def delete(order_id): 
        print(f"Cancelled order {order_id}")


class PaymentService:
    @staticmethod
    async def charge(amount):
        if amount > 1000:
            raise Exception("Payment declined")
        return {"charge_id": "CHG-456"}
    
    @staticmethod
    async def refund(charge_id):
        print(f"Refunded {charge_id}")


# NEW: Declarative saga definition
class OrderPlacementSaga(DeclarativeSaga):
    
    @step(name="create_order", aggregate_type="order")
    async def create_order(self, ctx):
        return await OrderService.create(ctx["order_data"])
    
    @compensate("create_order")
    async def cancel_order(self, ctx):
        await OrderService.delete(ctx["order_id"])
    
    @step(name="charge_payment", depends_on=["create_order"])
    async def charge_payment(self, ctx):
        return await PaymentService.charge(ctx["order_data"]["amount"])
    
    @compensate("charge_payment", depends_on=["create_order"])
    async def refund_payment(self, ctx):
        # This will wait for cancel_order to complete first!
        await PaymentService.refund(ctx["charge_id"])


# Setup (uses existing components)
async def main():
    pool = await create_pool(
        host='localhost',
        database='saga_db',
        user='saga_user',
        password='saga_pass'
    )
    
    # Existing components (no changes)
    storage = PostgresSagaStorage(pool)
    broker = await KafkaBroker.create('localhost:9092')
    optimistic_pub = OptimisticPublisher(storage, broker)
    
    # NEW: Create orchestrator
    orchestrator = IntegratedSagaOrchestrator(storage, optimistic_pub, pool)
    
    # Execute saga
    saga = OrderPlacementSaga()
    
    try:
        result = await saga.execute(
            orchestrator,
            saga_id=str(uuid4()),
            initial_context={
                "order_data": {
                    "items": ["WIDGET-001"],
                    "amount": 99.99
                }
            }
        )
        print("Success!", result)
    except Exception as exc:
        print("Failed (compensated):", exc)
    
    await broker.close()
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
```

## Summary: What Changed vs. What Stayed the Same

### ✅ UNCHANGED (Existing Implementation)
- `storage_postgres.py` - No modifications
- `outbox_worker.py` - No modifications
- `optimistic_publisher.py` - No modifications
- `outbox_statemachine.py` - No modifications
- Database schema - No changes
- Outbox polling - Still works the same
- Kafka integration - Still works the same

### ✨ NEW (3 Files Added)
- `compensation_graph.py` - Dependency resolution
- `saga_orchestrator.py` - Wires everything together
- `decorators.py` - User-friendly API

### 🔌 INTEGRATION POINTS
1. **Orchestrator → Storage**: Uses existing `load()`, `save()`, `append_outbox()`
2. **Orchestrator → Optimistic Publisher**: Uses existing `publish_after_commit()`
3. **Compensation → Outbox**: Each compensation creates outbox event
4. **Compensation → State Machine**: Status transitions via existing mechanisms

### 🎯 BENEFITS
- **Zero breaking changes** to existing code
- **Opt-in adoption** - use orchestrator when ready
- **Flexible compensation** - finally handles complex dependencies
- **Same guarantees** - outbox pattern, idempotency, state machines all still work

This is a **pure extension** - your existing outbox implementation keeps working exactly as before!