"""Tests for reliability demonstrations."""

import pytest

from sagaz.demonstrations.reliability.dlq_handling.main import _run as dlq_run
from sagaz.demonstrations.reliability.chaos_patterns.main import _run as chaos_run


@pytest.mark.asyncio
async def test_dlq_handling_demo():
    """Test DLQ handling demonstration."""
    await dlq_run()
    # If no exception is raised, the demo ran successfully


@pytest.mark.asyncio
async def test_chaos_patterns_demo():
    """Test chaos patterns demonstration."""
    await chaos_run()
    # If no exception is raised, the demo ran successfully
