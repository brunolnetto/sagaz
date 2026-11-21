"""The asset monitor's Gradio app (ADR-039).

``build_app`` lays out the views over an :class:`AssetSource`; every handler is
async and runs on Gradio's event loop, where the source opens its store on first
use. The app only reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sagaz.visualization.gradio import _data as data

if TYPE_CHECKING:
    from sagaz.core.storage.interfaces import SagaStorage
    from sagaz.core.storage.saga_log import SagaLogStore

COORDINATIONS = ["", "orchestrated", "choreographed"]
STATUSES = ["", "executing", "compensating", "completed", "compensated", "rolled_back", "failed"]


class AssetSource:
    """What the monitor reads: a unified saga log, or a classic saga storage.

    Each is a store instance or a URL, opened lazily on the app's event loop
    (asyncpg pools belong to the loop that creates them).
    """

    def __init__(
        self,
        saga_log: SagaLogStore | str | None = None,
        storage: SagaStorage | str | None = None,
    ) -> None:
        if (saga_log is None) == (storage is None):
            msg = "give exactly one of saga_log or storage"
            raise ValueError(msg)
        self._saga_log = saga_log
        self._storage = storage
        self._manager: Any = None

    @property
    def unified(self) -> bool:
        return self._saga_log is not None

    async def _log(self) -> SagaLogStore:
        if isinstance(self._saga_log, str):
            from sagaz.core.storage.saga_log import create_saga_log_store

            self._saga_log = create_saga_log_store(self._saga_log)
        return cast("SagaLogStore", self._saga_log)  # unified mode: __init__ checked it is set

    async def _classic(self) -> SagaStorage:
        if isinstance(self._storage, str):
            from sagaz.core.storage import create_storage_manager

            self._manager = create_storage_manager(url=self._storage)
            await self._manager.initialize()
            self._storage = self._manager.saga
        return cast("SagaStorage", self._storage)  # classic mode: a URL was resolved above

    async def rows(
        self, coordination: str, flow: str, status: str, tenant: str
    ) -> list[dict[str, Any]]:
        if self.unified:
            return await data.list_transactions(
                await self._log(),
                coordination=coordination or None,
                flow=flow.strip() or None,
                status=status or None,
                tenant=tenant.strip() or None,
            )
        rows = await data.list_sagas(await self._classic(), status=status or None)
        flow = flow.strip()
        return [r for r in rows if not flow or r["flow"] == flow]

    async def detail(self, tenant: str, transaction_id: str) -> dict[str, Any] | None:
        if self.unified:
            return await data.transaction_detail(await self._log(), tenant, transaction_id)
        return await data.saga_detail(await self._classic(), tenant, transaction_id)

    async def close(self) -> None:
        if self._manager is not None:
            await self._manager.close()
        elif self._saga_log is not None and not isinstance(self._saga_log, str):
            await self._saga_log.close()


def _table(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> list[list[Any]]:
    return [[row.get(c) for c in columns] for row in rows]


def build_app(source: AssetSource, *, title: str = "Sagaz assets") -> Any:
    """The monitor as ``gr.Blocks`` (call ``.launch()`` on it, or mount it)."""
    import gradio as gr

    async def refresh(coordination: str, flow: str, status: str, tenant: str):
        rows = await source.rows(coordination, flow, status, tenant)
        return _table(rows, data.TRANSACTION_COLUMNS), f"{len(rows)} transaction(s)"

    async def select(table: Any, event: Any):
        values = table.values.tolist() if hasattr(table, "values") else table
        row = values[event.index[0]] if event.index is not None else None
        if not row:
            return "", "", [], [], {}
        tenant, transaction_id = row[0], row[1]
        detail = await source.detail(tenant, transaction_id)
        if detail is None:
            return f"**{transaction_id}**: not found", "", [], [], {}
        header = (
            f"**{detail['transaction']}** · {detail['coordination']} · "
            f"status **{detail['status']}** · tenant {tenant}"
        )
        return (
            header,
            data.mermaid_markdown(detail["mermaid"]),
            _table(detail["steps"], data.STEP_COLUMNS),
            _table(detail["events"], data.EVENT_COLUMNS),
            data.as_json(detail["context"]),
        )

    # Gradio passes the selection to a parameter annotated with the SelectData
    # class itself; under ``from __future__ import annotations`` it would be a string.
    select.__annotations__["event"] = gr.SelectData

    with gr.Blocks(title=title) as app:
        gr.Markdown(f"# {title}\nPersisted saga state, read-only (ADR-039).")
        with gr.Row():
            coordination = gr.Dropdown(COORDINATIONS, value="", label="Coordination")
            flow = gr.Textbox(label="Flow", placeholder="any")
            status = gr.Dropdown(STATUSES, value="", label="Status")
            tenant = gr.Textbox(label="Tenant", placeholder="every tenant")
            button = gr.Button("Refresh", variant="primary")
        count = gr.Markdown()
        transactions = gr.Dataframe(
            headers=list(data.TRANSACTION_COLUMNS), interactive=False, label="Transactions"
        )
        header = gr.Markdown()
        with gr.Tabs():
            with gr.Tab("Diagram"):
                diagram = gr.Markdown()
            with gr.Tab("Steps"):
                steps = gr.Dataframe(headers=list(data.STEP_COLUMNS), interactive=False)
            with gr.Tab("Events"):
                events = gr.Dataframe(headers=list(data.EVENT_COLUMNS), interactive=False)
            with gr.Tab("Context"):
                context = gr.JSON()
        filters = [coordination, flow, status, tenant]
        button.click(refresh, filters, [transactions, count])
        app.load(refresh, filters, [transactions, count])
        transactions.select(select, transactions, [header, diagram, steps, events, context])
    return app
