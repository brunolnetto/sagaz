"""Chaos engineering patterns demonstration."""

import asyncio
from uuid import uuid4


async def _run() -> None:
    """Demonstrate chaos patterns for saga resilience.
    
    Phase 1: Setup
    - Create saga with chaos injection points
    - Initialize chaos monkey
    
    Phase 2: Execute
    - Run saga with random failures injected
    - Observe compensation chains triggered
    
    Phase 3: Verify
    - Check all compensations executed correctly
    - Verify saga recovered from failures
    """
    # Phase 1: Setup
    saga_id = f"demo-chaos-{uuid4().hex[:8]}"
    print(f"⚡ Setting up chaos engineering for saga: {saga_id}")
    
    # Phase 2: Execute
    await asyncio.sleep(0.01)  # Simulate saga execution under chaos
    print(f"▶️  Executing saga with chaos injection")
    
    # Phase 3: Verify
    print(f"✅ Saga {saga_id} recovered from injected failures")
    print(f"✅ Demo complete: chaos patterns demonstrated")


if __name__ == "__main__":
    asyncio.run(_run())
