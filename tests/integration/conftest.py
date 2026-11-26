"""Every test under ``tests/integration`` is an integration test.

CI's unit job runs ``-m "not integration"`` with the coverage gate, and the integration
job runs ``-m integration``. A test in this directory that forgot the marker used to run
in the unit job: 53 of them did, benchmarks included, which made the unit job slower and
flaky without adding coverage. The marker is now added here, so the directory decides.

Tests elsewhere (for example a backend's tests next to its unit tests) still mark
themselves ``integration`` when they need a service.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_HERE = Path(__file__).parent


@pytest.hookimpl(tryfirst=True)  # before ``-m`` selects on markers
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if _HERE in item.path.parents:
            item.add_marker(pytest.mark.integration)
