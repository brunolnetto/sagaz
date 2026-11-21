"""storage_layout="classic" is the table-per-concern layout; "legacy" is its alias (#578)."""

from __future__ import annotations

import pytest

from sagaz import Saga, SagaConfig, action
from sagaz.core.storage.event_store import InMemoryEventStore
from sagaz.core.storage.event_store.recorder import event_sourcing_settings, normalize_layout


def test_classic_is_the_default():
    assert SagaConfig(metrics=False, logging=False).storage_layout == "classic"


def test_legacy_is_an_alias_of_classic():
    assert SagaConfig(storage_layout="legacy", metrics=False, logging=False).storage_layout == (
        "classic"
    )
    assert normalize_layout("legacy") == "classic"
    assert normalize_layout("unified") == "unified"


@pytest.mark.parametrize("layout", ["classic", "legacy"])
def test_both_names_record_on_the_event_store(layout):
    store = InMemoryEventStore()

    class Order(Saga):
        saga_name = "order"

        class Meta:
            storage_layout = layout
            storage_strategy = "event_sourced"
            event_store = store

        @action("a")
        async def a(self, ctx): ...

    settings = event_sourcing_settings(Order(config=SagaConfig(metrics=False, logging=False)))
    assert settings is not None
    assert settings[0] is store


def test_an_unknown_layout_names_the_valid_ones():
    class Order(Saga):
        saga_name = "order"

        class Meta:
            storage_layout = "tables"

        @action("a")
        async def a(self, ctx): ...

    with pytest.raises(ValueError, match="'classic' or 'unified'"):
        event_sourcing_settings(Order(config=SagaConfig(metrics=False, logging=False)))
