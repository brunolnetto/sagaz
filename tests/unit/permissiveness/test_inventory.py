"""sagaz must not start accepting more invalid definitions and settings (#660).

``known_accepted.json`` lists what it accepts today and should refuse. The list can only
shrink: a fix removes its entries, and nothing is added to it.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.permissiveness import inventory
from tests.unit.permissiveness.cases import CASES

KNOWN = json.loads(inventory.KNOWN.read_text())

MEASURES = {
    "cases": inventory.accepted_cases,
    "configuration_fields": inventory.accepted_fields,
    "cli_options": inventory.unbounded_cli_options,
}


@pytest.mark.parametrize("kind", sorted(MEASURES))
def test_nothing_new_is_accepted(kind):
    newly_accepted = MEASURES[kind]() - set(KNOWN[kind])
    assert sorted(newly_accepted) == [], "sagaz accepts these invalid values: refuse them"


def known(kind: str) -> set[str]:
    """The known entries this environment can check (a class it cannot import is skipped)."""
    if kind != "configuration_fields":
        return set(KNOWN[kind])
    probed = inventory.probed_classes()
    return {entry for entry in KNOWN[kind] if entry.split(".")[0] in probed}


@pytest.mark.parametrize("kind", sorted(MEASURES))
def test_fixed_entries_leave_the_list(kind):
    now_refused = known(kind) - MEASURES[kind]()
    assert sorted(now_refused) == [], "now refused: remove them from known_accepted.json"


def test_every_known_case_is_still_probed():
    assert sorted(set(KNOWN["cases"]) - set(CASES)) == []


def test_the_inventory_measures_something():
    assert len(CASES) > 60
    assert KNOWN["configuration_fields"]
