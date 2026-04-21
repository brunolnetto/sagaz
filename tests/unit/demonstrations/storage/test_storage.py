"""Tests for storage demonstrations."""

import pytest

from sagaz.demonstrations.storage.event_sourcing.main import _run


@pytest.mark.asyncio
async def test_event_sourcing_demo():
    """Test event sourcing demonstration."""
    await _run()
    # If no exception is raised, the demo ran successfully
