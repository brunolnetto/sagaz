"""Gradio monitor of persisted saga assets (ADR-039): ``pip install 'sagaz[gradio]'``.

    from sagaz.visualization.gradio import launch
    launch(saga_log="postgresql://...")          # or storage="sqlite:///sagas.db"

``sagaz monitor --ui gradio --saga-log URL`` does the same from the command line.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sagaz.visualization.gradio._app import AssetSource, build_app

if TYPE_CHECKING:
    from sagaz.core.storage.interfaces import SagaStorage
    from sagaz.core.storage.saga_log import SagaLogStore


def launch(
    *,
    saga_log: SagaLogStore | str | None = None,
    storage: SagaStorage | str | None = None,
    host: str = "127.0.0.1",
    port: int = 7860,
    open_browser: bool = False,
    **launch_kwargs: Any,
) -> Any:
    """Build the monitor over *saga_log* or *storage* (a store or a URL) and serve it."""
    app = build_app(AssetSource(saga_log=saga_log, storage=storage))
    return app.launch(server_name=host, server_port=port, inbrowser=open_browser, **launch_kwargs)


__all__ = ["AssetSource", "build_app", "launch"]
