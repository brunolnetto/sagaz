"""The Gradio asset monitor (ADR-039, #501): data layer, app and CLI."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from sagaz.cli.app import cli
from sagaz.core.storage.saga_log import InMemorySagaLogStore
from sagaz.core.types import SagaStatus
from sagaz.visualization.gradio import _data as data
from sagaz.visualization.gradio._app import AssetSource

pytest.importorskip("duckdb")  # the scenarios below come from the analytics tests
pytest.importorskip("sqldim")

from tests.unit.analytics.test_unified_analytics import fill  # noqa: E402


@pytest.fixture
async def log():
    store = InMemorySagaLogStore()
    await fill(store)
    yield store
    await store.close()


class TestUnifiedLog:
    async def test_transactions_of_every_tenant_with_filters(self, log):
        rows = await data.list_transactions(log)
        assert {(r["coordination"], r["flow"]) for r in rows} == {
            ("orchestrated", "order"),
            ("choreographed", "order.created"),
        }
        assert len(rows) == 6
        assert set(rows[0]) == set(data.TRANSACTION_COLUMNS)
        choreographed = await data.list_transactions(log, coordination="choreographed")
        assert {r["coordination"] for r in choreographed} == {"choreographed"}
        failed = await data.list_transactions(log, status="failed")
        assert [r["transaction"] for r in failed] == ["orch-stuck"]
        assert await data.list_transactions(log, tenant="nobody") == []

    async def test_an_orchestrated_transaction(self, log):
        detail = await data.transaction_detail(log, "default", "orch-bad")
        assert detail["coordination"] == "orchestrated"
        steps = {s["step"]: s for s in detail["steps"]}
        assert steps["charge"]["status"] == "failed"
        assert "card declined" in steps["charge"]["error"]
        assert "__transaction__" not in steps
        assert [e["event"] for e in detail["events"]][0] == "SagaStarted"
        diagram = detail["mermaid"]
        assert diagram.startswith("flowchart LR")
        assert "s0 --> s1" in diagram
        assert "classDef failed" in diagram

    async def test_a_choreographed_transaction_is_a_causation_graph(self, log):
        (row,) = await data.list_transactions(
            log, coordination="choreographed", status="rolled_back"
        )
        detail = await data.transaction_detail(log, row["tenant"], row["transaction"])
        diagram = detail["mermaid"]
        assert '"orders: order.created"' in diagram
        assert "e0 --> e1" in diagram  # inventory.reserved was caused by order.created
        assert "classDef compensated" in diagram
        assert "classDef failed" in diagram  # the compensation request
        caused = [e for e in detail["events"] if e["caused_by"]]
        assert caused

    async def test_unknown_transactions(self, log):
        assert await data.transaction_detail(log, "default", "nope") is None

    def test_diagrams_of_nothing_and_unsafe_labels(self):
        assert 'empty["no steps recorded"]' in data.steps_diagram([])
        assert 'empty["no events recorded"]' in data.causation_diagram([])
        assert data._label('a"b<c>[d]{e}|f') == "abcdef"
        assert data.mermaid_markdown("flowchart LR").startswith("```mermaid\n")
        assert data.as_json({"at": data.datetime(2026, 1, 1)}) == {"at": "2026-01-01 00:00:00"}


class TestLegacyStorage:
    async def test_sagas_and_their_steps(self, tmp_path):
        from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage

        async with SQLiteSagaStorage(str(tmp_path / "sagas.db")) as storage:
            await storage.save_saga_state(
                "s-1",
                "checkout",
                SagaStatus.ROLLED_BACK,
                [
                    {"name": "reserve", "status": "compensated", "retry_count": 0},
                    {"name": "charge", "status": "failed", "error": "declined", "retry_count": 2},
                ],
                {"order_id": "o-1"},
            )
            (row,) = await data.list_sagas(storage)
            assert (row["transaction"], row["flow"], row["status"]) == (
                "s-1",
                "checkout",
                "rolled_back",
            )
            assert await data.list_sagas(storage, status="completed") == []
            detail = await data.saga_detail(storage, "default", "s-1")
            assert [s["attempt"] for s in detail["steps"]] == [1, 3]
            assert detail["context"] == {"order_id": "o-1"}
            assert "s0 --> s1" in detail["mermaid"]
            assert await data.saga_detail(storage, "default", "nope") is None


class TestSource:
    def test_exactly_one_source(self):
        with pytest.raises(ValueError, match="exactly one"):
            AssetSource()
        with pytest.raises(ValueError, match="exactly one"):
            AssetSource(saga_log="memory://", storage="memory://")

    async def test_a_log_url_opens_lazily(self):
        source = AssetSource(saga_log="memory://")
        assert await source.rows("", "", "", "") == []
        assert await source.detail("default", "nope") is None
        await source.close()

    async def test_a_storage_url(self, tmp_path):
        source = AssetSource(storage=f"sqlite:///{tmp_path / 's.db'}")
        assert await source.rows("", "checkout", "", "") == []
        await source.close()


class TestApp:
    async def test_the_handlers(self, log):
        gr = pytest.importorskip("gradio")
        from sagaz.visualization.gradio._app import build_app

        app = build_app(AssetSource(saga_log=log), title="Test")
        handlers = {f.fn.__name__: f.fn for f in app.fns.values() if f.fn is not None}
        table, count = await handlers["refresh"]("", "", "", "")
        assert count == "6 transaction(s)"
        index = next(i for i, row in enumerate(table) if row[1] == "orch-bad")
        selected = gr.SelectData(None, {"index": [index, 1], "value": "orch-bad"})
        header, diagram, steps, events, context = await handlers["select"](table, selected)
        assert "**orch-bad**" in header
        assert diagram.startswith("```mermaid")
        assert any(row[0] == "charge" for row in steps)
        assert events
        missing = [["default", "nope", *[""] * 6]]
        header, *_ = await handlers["select"](
            missing, gr.SelectData(None, {"index": [0, 1], "value": "nope"})
        )
        assert "not found" in header


class TestCli:
    def test_the_gradio_monitor_needs_a_source(self):
        result = CliRunner().invoke(
            cli,
            ["monitor", "--ui", "gradio"],
            env={"SAGAZ_SAGA_LOG_URL": None, "SAGAZ_STORAGE_URL": None},
        )
        assert result.exit_code != 0
        assert "--saga-log" in result.output

    def test_without_gradio(self, monkeypatch):
        import importlib.util

        real = importlib.util.find_spec
        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name, *a: None if name == "gradio" else real(name, *a),
        )
        result = CliRunner().invoke(cli, ["monitor", "--ui", "gradio", "--saga-log", "memory://"])
        assert result.exit_code != 0
        assert "sagaz[gradio]" in result.output

    def test_it_launches_on_loopback(self, monkeypatch):
        pytest.importorskip("gradio")
        calls = {}
        monkeypatch.setattr(
            "sagaz.visualization.gradio.launch", lambda **kwargs: calls.update(kwargs)
        )
        args = [
            "monitor",
            "--ui",
            "gradio",
            "--saga-log",
            "memory://",
            "--port",
            "7861",
            "--no-browser",
        ]
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0, result.output
        assert calls == {
            "saga_log": "memory://",
            "host": "127.0.0.1",
            "port": 7861,
            "open_browser": False,
        }
        exposed = CliRunner().invoke(cli, [*args, "--host", "0.0.0.0"])
        assert exposed.exit_code != 0  # needs --unsafe-expose
