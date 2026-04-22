"""Tests for integrations demonstrations."""

import pytest

from sagaz.demonstrations.integrations.multi_tenancy.main import _run


@pytest.mark.asyncio
async def test_multi_tenancy_demo():
    """Test multi-tenancy isolation demonstration."""
    await _run()
    # If no exception is raised, the demo ran successfully
