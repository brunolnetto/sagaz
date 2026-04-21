"""Tests for performance demonstrations."""

import pytest

from sagaz.demonstrations.performance.optimization_guide.main import _run


@pytest.mark.asyncio
async def test_optimization_guide_demo():
    """Test performance optimization guide demonstration."""
    await _run()
    # If no exception is raised, the demo ran successfully
