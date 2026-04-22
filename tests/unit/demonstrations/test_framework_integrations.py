"""Tests for framework_integrations demonstration modules."""

import asyncio
import importlib
import sys
from unittest.mock import patch

import pytest

# ===========================================================================
# fastapi_integration
# ===========================================================================


@pytest.mark.asyncio
async def test_fastapi_integration_run_function():
    """Test the full FastAPI integration demonstration end-to-end."""
    from sagaz.core.triggers.registry import TriggerRegistry
    from sagaz.demonstrations.framework_integrations.fastapi_integration.main import _run

    TriggerRegistry.clear()
    try:
        await _run()
    finally:
        TriggerRegistry.clear()


def test_fastapi_integration_main():
    with patch(
        "sagaz.demonstrations.framework_integrations.fastapi_integration.main.asyncio.run"
    ) as mock_run:
        mock_run.side_effect = lambda coro: coro.close()
        from sagaz.demonstrations.framework_integrations.fastapi_integration.main import main

        main()
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_fastapi_integration_import_error_path():
    """Covers the ImportError fallback (L37-40) when httpx is unavailable."""
    from sagaz.core.triggers.registry import TriggerRegistry

    TriggerRegistry.clear()
    with patch.dict(sys.modules, {"httpx": None}):
        import sagaz.demonstrations.framework_integrations.fastapi_integration.main as m

        importlib.reload(m)
        await m._run()
    TriggerRegistry.clear()
