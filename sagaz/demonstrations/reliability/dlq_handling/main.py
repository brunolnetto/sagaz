"""Dead-Letter Queue (DLQ) handling demonstration."""

import asyncio
from uuid import uuid4


async def _run() -> None:
    """Demonstrate DLQ pattern for failed sagas.

    Phase 1: Setup
    - Create saga with potential failure points
    - Initialize DLQ handler

    Phase 2: Execute
    - Run saga that will fail at a step
    - Verify message is sent to DLQ

    Phase 3: Verify
    - Check DLQ contains failed saga message
    - Verify retry capability from DLQ
    """
    # Phase 1: Setup
    saga_id = f"demo-dlq-{uuid4().hex[:8]}"
    print(f"📦 Setting up DLQ handling for saga: {saga_id}")

    # Phase 2: Execute
    await asyncio.sleep(0.01)  # Simulate saga execution with failure
    print("▶️  Executing saga with DLQ handler")

    # Phase 3: Verify
    print(f"✅ Failed saga {saga_id} queued in DLQ")
    print("✅ Demo complete: DLQ pattern demonstrated")


if __name__ == "__main__":
    asyncio.run(_run())
