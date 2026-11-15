"""Publication/slot management and connection helpers of the logical replication source."""

from __future__ import annotations

import sys
import types

import pytest

from sagaz.integrations.cdc import CDCError
from sagaz.integrations.cdc._pg_setup import (
    check_identifier,
    check_slot_name,
    default_connection_factory,
    drop,
    ensure_publication,
    ensure_slot,
    setup,
)
from tests.unit.integrations.cdc.fake_replication import FakeCursor, FakeServer


class TestNames:
    @pytest.mark.parametrize("name", ["saga_outbox", "_x1", "a$b"])
    def test_identifiers(self, name):
        assert check_identifier(name, "table name") == name

    def test_qualified(self):
        assert check_identifier("tenant.saga_outbox", "table", qualified=True)
        with pytest.raises(ValueError, match="invalid table"):
            check_identifier("tenant.saga_outbox", "table")

    @pytest.mark.parametrize("name", ["", "a-b", "x y", "a;b", "1a"])
    def test_bad_identifiers(self, name):
        with pytest.raises(ValueError):
            check_identifier(name, "publication name")

    def test_slot_names(self):
        assert check_slot_name("sagaz_outbox_2") == "sagaz_outbox_2"
        for bad in ("Upper", "a-b", "", "x" * 64):
            with pytest.raises(ValueError):
                check_slot_name(bad)


CREATE_SLOT = "SELECT pg_create_logical_replication_slot('s', 'pgoutput')"


class TestEnsure:
    def test_creates_then_is_idempotent(self):
        server = FakeServer()
        cursor = FakeCursor(server)
        assert ensure_publication(cursor, "pub", "saga_outbox") is True
        assert ensure_publication(cursor, "pub", "saga_outbox") is False
        assert ensure_slot(cursor, "slot") is True
        assert ensure_slot(cursor, "slot") is False
        assert "CREATE PUBLICATION pub FOR TABLE saga_outbox WITH (publish = 'insert')" in (
            server.statements
        )

    def test_concurrent_creation_is_tolerated(self):
        server = FakeServer()
        cursor = FakeCursor(server)
        checks = iter([False, True])

        def racing_exists():
            return next(checks)

        from sagaz.integrations.cdc._pg_setup import _create_idempotently

        server.create_error = RuntimeError("already exists")
        assert _create_idempotently(cursor, racing_exists, CREATE_SLOT, "slot") is False

    def test_creation_failure(self):
        server = FakeServer(create_error=RuntimeError("permission denied"))
        with pytest.raises(CDCError, match="cannot create publication 'pub': permission denied"):
            ensure_publication(FakeCursor(server), "pub", "saga_outbox")

    def test_setup_creates_publication_before_slot(self):
        server = FakeServer()
        setup(server.connect, "dsn", "slot", "pub", "saga_outbox")
        creates = [s for s in server.statements if not s.startswith("SELECT 1")]
        assert creates[0].startswith("CREATE PUBLICATION")
        assert "pg_create_logical_replication_slot('slot', 'pgoutput')" in creates[1]
        assert server.open_connections == 0

    def test_drop(self):
        server = FakeServer(slots={"slot": 5}, publications={"pub"})
        assert drop(server.connect, "dsn", "slot") is True
        assert server.publications == {"pub"}
        assert drop(server.connect, "dsn", "slot", "pub") is False
        assert server.publications == set()


class TestDefaultConnectionFactory:
    @pytest.fixture
    def fake_psycopg2(self, monkeypatch):
        calls = []

        class Conn:
            autocommit = False

        def connect(dsn, **kwargs):
            calls.append((dsn, kwargs))
            return Conn()

        extras = types.ModuleType("psycopg2.extras")
        extras.LogicalReplicationConnection = object  # type: ignore[attr-defined]
        module = types.ModuleType("psycopg2")
        module.connect = connect  # type: ignore[attr-defined]
        module.extras = extras  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "psycopg2", module)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)
        return calls

    def test_replication_connection(self, fake_psycopg2):
        default_connection_factory("dsn", True)
        assert fake_psycopg2 == [("dsn", {"connection_factory": object})]

    def test_ordinary_connection_is_autocommit(self, fake_psycopg2):
        conn = default_connection_factory("dsn", False)
        assert conn.autocommit is True
        assert fake_psycopg2 == [("dsn", {})]
