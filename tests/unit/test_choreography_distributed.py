"""The three-service order saga over Redis Streams, without Docker (#56).

Same scenario as tests/integration/test_choreography_order_saga.py, but every
service's bus talks to one in-process fake Redis: each participant still has
its own bus instance and consumer group, events still go through stream
serialization, and delivery is asynchronous, as between separate processes.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sagaz.choreography.buses import redis_streams
from tests.integration.test_choreography_order_saga import Deployment, _redis_bus
from tests.unit.core.storage.backends._fake_redis import FakeRedis


class _Container:
    def get_container_host_ip(self) -> str:
        return "fake"

    def get_exposed_port(self, port: int) -> int:
        return port


@pytest.fixture
def make_bus():
    shared = FakeRedis()
    with patch.object(redis_streams.aioredis, "from_url", lambda *a, **k: shared):
        yield lambda group: _redis_bus(_Container(), "orders.fake", group)


async def test_order_completes_across_services(make_bus):
    async with Deployment(make_bus) as deployment:
        start = await deployment.orders.begin(
            "order.created", {"order_id": "o-1", "amount": 40}, tenant_id="acme"
        )
        status = await deployment.settled(start.saga_id, timeout=10)

    assert (status.status, status.tenant_id) == ("completed", "acme")
    assert deployment.inventory.tenants == ["acme"]  # tenant crossed the stream
    assert deployment.payments.charged == ["o-1"]


async def test_declined_payment_is_compensated_across_services(make_bus):
    async with Deployment(make_bus) as deployment:
        start = await deployment.orders.begin("order.created", {"order_id": "o-2", "amount": 500})
        status = await deployment.settled(start.saga_id, timeout=10)

    assert status.status == "compensated"
    assert status.failure["participant"] == "payments"
    assert deployment.inventory.released == ["o-2"]
