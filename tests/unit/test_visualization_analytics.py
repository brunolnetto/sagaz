"""/api/v1/analytics/* — Gold-layer reports served by the visualization monitor."""

from __future__ import annotations

import builtins

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("duckdb")

from sagaz import Saga, action, compensate  # noqa: E402
from sagaz.core.config import SagaConfig  # noqa: E402
from sagaz.core.storage.backends.memory.saga import InMemorySagaStorage  # noqa: E402
from sagaz.core.storage.backends.sqlite.saga import SQLiteSagaStorage  # noqa: E402
from sagaz.visualization import analytics_api  # noqa: E402
from sagaz.visualization.server import create_app  # noqa: E402


class PaymentSaga(Saga):
    saga_name = "payment"

    @action("authorize")
    async def authorize(self, ctx):
        return {"auth": True}

    @compensate("authorize")
    async def void(self, ctx):
        return None

    @action("capture", depends_on=["authorize"])
    async def capture(self, ctx):
        if ctx.get("fail"):
            msg = "capture failed"
            raise RuntimeError(msg)
        return {"captured": True}


async def _seed(storage) -> None:
    config = SagaConfig(storage=storage)
    await PaymentSaga(config=config).run({"n": 1})
    with pytest.raises(RuntimeError):
        await PaymentSaga(config=config).run({"n": 2, "fail": True})


@pytest.fixture
async def seeded_storage():
    storage = InMemorySagaStorage()
    await _seed(storage)
    return storage


class TestAnalyticsReports:
    def test_index_lists_reports_and_configuration(self, seeded_storage):
        with TestClient(create_app(analytics_storage=seeded_storage)) as client:
            body = client.get("/api/v1/analytics").json()
        assert body == {
            "reports": ["compensations", "lifecycle", "step-latency", "summary"],
            "configured": True,
        }

    def test_summary_comes_from_the_gold_layer(self, seeded_storage):
        with TestClient(create_app(analytics_storage=seeded_storage)) as client:
            body = client.get("/api/v1/analytics/summary").json()
        row = body["rows"][0]
        assert body["report"] == "summary"
        assert body["sagas_loaded"] == 2
        assert body["quality_errors"] == 0
        assert (row["saga_name"], row["total_sagas"], row["completed"]) == ("payment", 2, 1)

    def test_step_latency_reports_percentiles_per_step(self, seeded_storage):
        with TestClient(create_app(analytics_storage=seeded_storage)) as client:
            rows = client.get("/api/v1/analytics/step-latency").json()["rows"]
        by_step = {r["step_name"]: r for r in rows}
        assert set(by_step) == {"authorize", "capture"}
        assert by_step["capture"]["error_rate_pct"] == pytest.approx(50.0)
        assert by_step["authorize"]["p95_ms"] is not None

    def test_compensations_and_lifecycle_reports(self, seeded_storage):
        with TestClient(create_app(analytics_storage=seeded_storage)) as client:
            compensations = client.get("/api/v1/analytics/compensations").json()["rows"]
            lifecycle = client.get("/api/v1/analytics/lifecycle").json()["rows"]
        assert compensations[0]["step_name"] == "authorize"
        assert len(lifecycle) == 2
        assert isinstance(lifecycle[0]["created_at"], str)  # datetimes are JSON-encoded

    def test_unknown_report_is_404(self, seeded_storage):
        with TestClient(create_app(analytics_storage=seeded_storage)) as client:
            response = client.get("/api/v1/analytics/nope")
        assert response.status_code == 404
        assert "available" in response.json()["detail"]


class TestAnalyticsConfiguration:
    def test_without_storage_reports_explain_how_to_configure(self):
        with TestClient(create_app()) as client:
            index = client.get("/api/v1/analytics").json()
            response = client.get("/api/v1/analytics/summary")
        assert index["configured"] is False
        assert response.status_code == 503
        assert "--storage-url" in response.json()["detail"]

    def test_without_the_extra_reports_answer_501(self, seeded_storage, monkeypatch):
        real_import = builtins.__import__

        def no_analytics(name, *args, **kwargs):
            if name == "sagaz.analytics":
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_analytics)
        with TestClient(create_app(analytics_storage=seeded_storage)) as client:
            response = client.get("/api/v1/analytics/summary")
        assert response.status_code == 501
        assert "sagaz[analytics]" in response.json()["detail"]

    async def test_storage_url_is_opened_for_the_app_lifetime(self, tmp_path):
        db = tmp_path / "sagas.db"
        sqlite = SQLiteSagaStorage(str(db))
        await _seed(sqlite)
        await sqlite.close()

        app = create_app(analytics_storage_url=f"sqlite://{db}")
        assert app.state.analytics_storage is None
        with TestClient(app) as client:
            body = client.get("/api/v1/analytics/summary").json()
            assert app.state.analytics_storage is not None
        assert body["rows"][0]["total_sagas"] == 2


def test_report_names_map_to_existing_queries():
    from sagaz.analytics import SagaQueries

    for attribute in analytics_api.ANALYTICS_REPORTS.values():
        assert isinstance(getattr(SagaQueries, attribute), str)
