"""Tests for backward-compatible StateChart snapshot serialization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sagaz.core.replay import SagaSnapshot


def test_snapshot_round_trip_preserves_active_configuration() -> None:
    snapshot = SagaSnapshot.create(
        saga_id=uuid4(),
        saga_name="OrderSaga",
        step_name="reserve_inventory",
        step_index=1,
        status="executing",
        context={"order_id": "order-123"},
        completed_steps=["validate_order"],
        configuration=["executing"],
    )

    restored = SagaSnapshot.from_dict(snapshot.to_dict())

    assert restored.configuration == ["executing"]
    assert restored.status == snapshot.status
    assert restored.context == snapshot.context
    assert restored.completed_steps == snapshot.completed_steps


def test_legacy_snapshot_without_configuration_uses_status_fallback() -> None:
    snapshot = SagaSnapshot.create(
        saga_id=uuid4(),
        saga_name="OrderSaga",
        step_name="charge_payment",
        step_index=2,
        status="compensating",
        context={},
        completed_steps=["validate_order", "reserve_inventory"],
    )
    legacy_payload = snapshot.to_dict()
    legacy_payload.pop("configuration")

    restored = SagaSnapshot.from_dict(legacy_payload)

    assert restored.configuration == ["compensating"]


def test_snapshot_optional_positional_arguments_keep_their_legacy_order() -> None:
    created_at = datetime.now(UTC)
    retention_until = created_at + timedelta(days=7)
    external_refs = {"payload": "blob://snapshot/payload"}

    snapshot = SagaSnapshot(
        uuid4(),
        uuid4(),
        "OrderSaga",
        "step",
        0,
        "pending",
        {},
        [],
        created_at,
        retention_until,
        external_refs,
    )

    assert snapshot.retention_until == retention_until
    assert snapshot.external_refs == external_refs
    assert snapshot.configuration == []
