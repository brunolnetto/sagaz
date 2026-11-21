"""The examples are grouped by industry (the domains of Apache Airflow's user survey)."""

from __future__ import annotations

import importlib

import pytest

from sagaz.cli._examples_discovery import (
    DOMAIN_FOLDERS,
    DOMAIN_MAPPING,
    get_examples_dir,
    resolve_domain,
)
from sagaz.core.exceptions import SagaFailedError


def test_every_mapped_subdomain_exists_and_subdomains_are_unique():
    examples = get_examples_dir()
    subdomains = [s for subs in DOMAIN_MAPPING.values() for s in subs]
    assert len(subdomains) == len(set(subdomains))
    for display, subs in DOMAIN_MAPPING.items():
        for sub in subs:
            assert (examples / DOMAIN_FOLDERS[display] / sub).is_dir(), (display, sub)


def test_every_example_sits_in_a_mapped_subdomain():
    examples = get_examples_dir()
    mapped = {(DOMAIN_FOLDERS[d], s) for d, subs in DOMAIN_MAPPING.items() for s in subs}
    found = {
        (main.parent.parent.parent.name, main.parent.parent.name)
        for name in ("main.py", "demo.py")
        for main in examples.glob(f"*/*/*/{name}")
    }
    assert found <= mapped, found - mapped


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Consumer Goods", "Consumer Goods"),
        ("consumer_goods", "Consumer Goods"),
        ("software & technology", "Software & Technology"),
        ("nope", None),
    ],
)
def test_domains_resolve_by_display_or_folder_name(given, expected):
    assert resolve_domain(given, DOMAIN_FOLDERS) == expected


CONSUMER_GOODS = [
    ("product.product_launch", "ProductLaunchSaga", {"fail_at": "book_distribution"}),
    ("product.product_recall", "ProductRecallSaga", {"defect_confirmed": False}),
    ("distribution.retail_replenishment", "RetailReplenishmentSaga", {"no_carrier": True}),
    ("distribution.trade_promotion", "TradePromotionSaga", {"line_down": True}),
    (
        "direct_to_consumer.subscription_box",
        "SubscriptionBoxSaga",
        {"missing_item": "trail-mix"},
    ),
    (
        "direct_to_consumer.returns_processing",
        "ReturnsProcessingSaga",
        {"condition": "not_ours"},
    ),
    ("supply.co_packer_order", "CoPackerOrderSaga", {"sample_rejected": True}),
    (
        "supply.packaging_switch",
        "PackagingSwitchSaga",
        {"artwork": {"nutrition_panel": True, "barcode": True}},
    ),
]


@pytest.mark.parametrize(("module", "cls", "failure"), CONSUMER_GOODS)
async def test_consumer_goods_examples_complete_and_compensate(module, cls, failure, monkeypatch):
    mod = importlib.import_module(f"sagaz.examples.consumer_goods.{module}.main")
    monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
    saga_cls = getattr(mod, cls)
    base = {
        "sku": "S",
        "launch_units": 1,
        "retailers": ["R"],
        "recall_id": "RC",
        "lot": "L",
        "retailer_dc": "DC",
        "promo_id": "P",
        "retailer": "R",
        "discount_per_unit": "0.5",
        "expected_units": 10,
        "subscriber_id": "SUB",
        "box_items": ["a"],
        "order_id": "O",
        "amount": "1.00",
        "co_packer": "C",
        "materials": ["m"],
        "cases": 1,
        "new_supplier": "N",
        "old_supplier": "D",
        "artwork": {"version": "v1", "allergens": True, "nutrition_panel": True, "barcode": True},
    }
    saga = saga_cls()
    await saga.run(dict(base))
    pivots = [s.step_id for s in saga.get_steps() if s.pivot]
    assert len(pivots) == 1
    assert pivots[0] in saga._completed_pivots  # the run went through its pivot

    with pytest.raises(SagaFailedError):
        await saga_cls().run({**base, **failure})


async def _no_sleep(_seconds: float) -> None:
    return None


def _declared_pivots() -> list[tuple[str, str]]:
    """(module, step) for every example whose docstring declares a ``Pivot Step:``."""
    examples = get_examples_dir()
    found = []
    for main in sorted(examples.glob("*/*/*/main.py")):
        text = main.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("Pivot Step:"):
                module = ".".join(main.relative_to(examples).with_suffix("").parts)
                found.append((module, line.split(":", 1)[1].strip()))
    return found


@pytest.mark.parametrize(("module", "step"), _declared_pivots())
def test_a_declared_pivot_is_a_pivot_step(module, step):
    """An example that says a step is its pivot marks it ``pivot=True``."""
    mod = importlib.import_module(f"sagaz.examples.{module}")
    sagas = [
        obj
        for obj in vars(mod).values()
        if isinstance(obj, type)
        and getattr(obj, "__module__", "") == mod.__name__
        and hasattr(obj, "get_steps")
    ]
    pivots = {s.step_id for saga in sagas for s in saga().get_steps() if s.pivot}
    assert step in pivots, f"{module}: {step} is described as the pivot but is not pivot=True"
