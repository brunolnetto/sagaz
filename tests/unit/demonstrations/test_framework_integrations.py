"""Tests for framework_integrations demonstration modules."""

import asyncio
from unittest.mock import patch

import pytest


# ===========================================================================
# fastapi_integration
# ===========================================================================


@pytest.mark.asyncio
async def test_fastapi_integration_run_function():
    """Test the full FastAPI integration demonstration end-to-end."""
    from sagaz.demonstrations.framework_integrations.fastapi_integration.main import _run
    from sagaz.core.triggers.registry import TriggerRegistry

    TriggerRegistry.clear()
    try:
        await _run()
    finally:
        TriggerRegistry.clear()


def test_fastapi_integration_main():
    with patch(
        "sagaz.demonstrations.framework_integrations.fastapi_integration.main.asyncio.run"
    ) as mock_run:
        from sagaz.demonstrations.framework_integrations.fastapi_integration.main import main

        main()
        mock_run.assert_called_once()
