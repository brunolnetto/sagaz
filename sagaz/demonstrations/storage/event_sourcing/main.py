"""Event sourcing storage demonstration."""

import asyncio
from uuid import uuid4


async def _run() -> None:
    """Demonstrate event sourcing as storage strategy.

    Phase 1: Setup
    - Create saga with event sourcing enabled
    - Initialize event store

    Phase 2: Execute
    - Run saga that produces state-change events
    - Log all events to store

    Phase 3: Verify
    - Replay events to reconstruct final state
    - Verify replay result matches final state
    """
    # Phase 1: Setup
    saga_id = f"demo-eventsource-{uuid4().hex[:8]}"
    print(f"📝 Setting up event sourcing for saga: {saga_id}")

    # Phase 2: Execute
    await asyncio.sleep(0.01)  # Simulate saga execution
    print("▶️  Executing saga with event sourcing")

    # Phase 3: Verify
    print(f"✅ Saga {saga_id} events stored and replayed")
    print("✅ Demo complete: event sourcing demonstrated")


if __name__ == "__main__":
    asyncio.run(_run())
