#!/usr/bin/env python3
"""
FastAPI Integration — request-scoped saga execution with webhook router

Demonstrates:
  1. Sagaz lifespan hooks (sagaz_startup / sagaz_shutdown)
  2. Webhook router (create_webhook_router) for event-driven saga triggers
  3. Correlation ID propagation via X-Correlation-ID header
  4. Webhook status tracking (get_webhook_status)

Runs a self-contained FastAPI app with an in-process httpx test client.
No external infrastructure required (no uvicorn server started).

Prerequisites:
    pip install fastapi httpx

Usage:
    sagaz demo run fastapi_integration
    python -m sagaz.demonstrations.fastapi_integration.main
"""

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("sagaz.demo.fastapi_integration")


async def _run() -> None:
    try:
        from contextlib import asynccontextmanager

        import httpx
        from fastapi import FastAPI
    except ImportError as exc:
        print(f"\n  Missing dependency: {exc}")
        print("  Install with: pip install fastapi httpx")
        return

    from sagaz import Saga, SagaConfig, action, compensate, configure
    from sagaz.core.triggers.decorators import trigger
    from sagaz.core.triggers.registry import TriggerRegistry
    from sagaz.integrations.fastapi import (
        create_webhook_router,
        get_webhook_status,
        sagaz_shutdown,
        sagaz_startup,
    )

    # Clean trigger registry to avoid interference from other demos
    TriggerRegistry.clear()

    # ------------------------------------------------------------------
    # Define a saga that can be triggered via webhook
    # ------------------------------------------------------------------

    class OrderSaga(Saga):
        saga_name = "fastapi-order"

        @trigger(source="orders", idempotency_key="order_id")
        def on_order(self, event: dict) -> dict:
            return {
                "order_id": event["order_id"],
                "amount": event.get("amount", 0),
            }

        @action("create_order")
        async def create_order(self, ctx: dict) -> dict:
            logger.info(f"  ✓ Creating order {ctx.get('order_id')}")
            await asyncio.sleep(0.02)
            return {"created": True}

        @compensate("create_order")
        async def cancel_order(self, ctx: dict) -> None:
            logger.info(f"  ↩ Cancelling order {ctx.get('order_id')}")

        @action("charge", depends_on=["create_order"])
        async def charge(self, ctx: dict) -> dict:
            logger.info(f"  ✓ Charging ${ctx.get('amount', 0):.2f}")
            await asyncio.sleep(0.02)
            return {"charge_id": "CHG-1"}

        @compensate("charge")
        async def refund(self, ctx: dict) -> None:
            logger.info("  ↩ Refunding charge")

    # ------------------------------------------------------------------
    # Build the FastAPI app
    # ------------------------------------------------------------------

    configure(SagaConfig())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await sagaz_startup()
        yield
        await sagaz_shutdown()

    app = FastAPI(title="Sagaz Demo", lifespan=lifespan)
    app.include_router(create_webhook_router("/webhooks"))

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Run requests via in-process httpx client
    # ------------------------------------------------------------------

    from httpx import ASGITransport

    transport = ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Phase 1: Health check
        print("\n" + "=" * 60)
        print("Phase 1 — Health check")
        print("=" * 60)

        resp = await client.get("/health")
        print(f"\n  GET /health → {resp.status_code} {resp.json()}")

        # Phase 2: Fire webhook event
        print("\n" + "=" * 60)
        print("Phase 2 — POST /webhooks/orders (fire event)")
        print("=" * 60)

        resp = await client.post(
            "/webhooks/orders",
            json={"order_id": "ORD-500", "amount": 79.99},
            headers={"X-Correlation-ID": "demo-corr-001"},
        )
        body = resp.json()
        print(f"\n  POST /webhooks/orders → {resp.status_code}")
        print(f"  Response: {body}")

        correlation_id = body.get("correlation_id", "demo-corr-001")

        # Allow background saga to execute
        await asyncio.sleep(0.5)

        # Phase 3: Check webhook status
        print("\n" + "=" * 60)
        print("Phase 3 — GET /webhooks/orders/status/<correlation_id>")
        print("=" * 60)

        resp = await client.get(f"/webhooks/orders/status/{correlation_id}")
        print(f"\n  GET /webhooks/orders/status/{correlation_id} → {resp.status_code}")
        print(f"  Response: {resp.json()}")

        # Phase 4: Idempotent replay (same order_id)
        print("\n" + "=" * 60)
        print("Phase 4 — Duplicate webhook (idempotent replay)")
        print("=" * 60)

        resp = await client.post(
            "/webhooks/orders",
            json={"order_id": "ORD-500", "amount": 79.99},
        )
        print(f"\n  POST /webhooks/orders → {resp.status_code}")
        print(f"  Response: {resp.json()}")

        await asyncio.sleep(0.3)

        # Phase 5: Missing idempotency key
        print("\n" + "=" * 60)
        print("Phase 5 — Missing idempotency key (rejected)")
        print("=" * 60)

        resp = await client.post(
            "/webhooks/orders",
            json={"amount": 10.00},  # no order_id!
        )
        print(f"\n  POST /webhooks/orders → {resp.status_code}")
        print(f"  Response: {resp.json()}")

    # Clean up
    TriggerRegistry.clear()

    print("\n" + "=" * 60)
    print("Done — FastAPI integration demonstration complete")
    print("=" * 60 + "\n")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
