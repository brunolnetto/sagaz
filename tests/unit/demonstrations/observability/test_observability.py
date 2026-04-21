"""Tests for observability demonstrations."""

import pytest

from sagaz.demonstrations.observability.otel_tracing.main import _run


@pytest.mark.asyncio
async def test_otel_tracing_demo():
    """Test OTEL tracing demonstration."""
    await _run()
    # If no exception is raised, the demo ran successfully
