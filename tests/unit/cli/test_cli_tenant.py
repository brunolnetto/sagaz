"""`sagaz tenant` commands against real SQLite storage (ADR-020, #54)."""

from __future__ import annotations

import asyncio

import pytest
from click.testing import CliRunner

from sagaz.cli.app import cli
from sagaz.core.storage import create_storage_manager
from sagaz.core.tenant import TenantRegistry


@pytest.fixture
def storage_url(tmp_path, monkeypatch):
    url = f"sqlite://{tmp_path / 'tenants.db'}"
    monkeypatch.setenv("SAGAZ_STORAGE_URL", url)
    return url


def _sagaz(*args, input=None):
    return CliRunner().invoke(cli, ["tenant", *args], input=input)


def _registry(url):
    async def load():
        async with create_storage_manager(url=url) as manager:
            return await TenantRegistry.from_storage(manager.saga)

    return asyncio.run(load())


def test_create_list_and_reload_from_storage(storage_url):
    created = _sagaz("create", "acme", "--plan", "premium", "--max-concurrent-sagas", "5")
    assert created.exit_code == 0, created.output
    assert "Created acme  plan=premium  active  quotas: max_concurrent_sagas=5" in created.output

    listed = _sagaz("list")
    assert listed.output.strip() == "acme  plan=premium  active  quotas: max_concurrent_sagas=5"

    tenant = _registry(storage_url).get("acme")
    assert (tenant.plan, tenant.quotas.max_concurrent_sagas) == ("premium", 5)


def test_empty_registry(storage_url):
    assert _sagaz("list").output.strip() == "No tenants registered."


def test_quota_show_update_and_clear(storage_url):
    _sagaz("create", "acme", "--max-retries", "3")

    assert "max_retries=3" in _sagaz("quota", "acme").output
    updated = _sagaz("quota", "acme", "--max-step-duration", "2.5")
    assert "max_step_duration_seconds=2.5, max_retries=3" in updated.output
    cleared = _sagaz("quota", "acme", "--clear")
    assert "quotas: unlimited" in cleared.output
    assert _registry(storage_url).get("acme").quotas.max_retries is None


def test_suspend_and_activate(storage_url):
    _sagaz("create", "acme")
    assert "acme  plan=standard  suspended" in _sagaz("suspend", "acme").output
    assert _registry(storage_url).get("acme").active is False
    assert "acme  plan=standard  active" in _sagaz("activate", "acme").output


def test_delete_asks_for_confirmation(storage_url):
    _sagaz("create", "acme")

    aborted = _sagaz("delete", "acme", input="n\n")
    assert aborted.exit_code == 1
    assert "acme" in _registry(storage_url)

    deleted = _sagaz("delete", "acme", input="y\n")
    assert deleted.exit_code == 0
    assert "Deleted tenant 'acme'." in deleted.output
    assert "acme" not in _registry(storage_url)


def test_delete_with_yes(storage_url):
    _sagaz("create", "acme")
    assert _sagaz("delete", "acme", "--yes").exit_code == 0


@pytest.mark.parametrize(
    "args",
    [
        ("create", "acme"),  # duplicate (created in the test body first)
        ("quota", "ghost"),
        ("delete", "ghost", "--yes"),
        ("suspend", "ghost"),
    ],
)
def test_tenant_errors_are_reported_without_traceback(storage_url, args):
    _sagaz("create", "acme")
    result = _sagaz(*args)
    assert result.exit_code == 1
    assert result.output.startswith("Error:")


def test_invalid_tenant_id(storage_url):
    result = _sagaz("create", "Bad Id")
    assert result.exit_code == 2
    assert "Invalid tenant id 'Bad Id'" in result.output


def test_negative_quota_is_rejected_by_click(storage_url):
    assert _sagaz("create", "acme", "--max-retries", "-1").exit_code == 2


def test_storage_url_is_required(monkeypatch):
    monkeypatch.delenv("SAGAZ_STORAGE_URL", raising=False)
    result = _sagaz("list")
    assert result.exit_code == 2
    assert "--storage-url" in result.output
