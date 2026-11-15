"""The pgoutput decoder, against hand-built messages and bytes from a real server."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sagaz.integrations.cdc._pgoutput import (
    UNCHANGED_TOAST,
    Begin,
    Commit,
    Insert,
    PgOutputDecoder,
    PgOutputError,
    Relation,
    Skipped,
    decode_message,
    format_lsn,
    pg_timestamp,
)
from sagaz.integrations.cdc._types import CDCError
from tests.unit.integrations.cdc import pgoutput_encoder as enc

T0 = datetime(2026, 11, 14, 20, 0, 0, 123456, tzinfo=UTC)

# Captured with pg_logical_slot_peek_binary_changes(..., 'proto_version', '1',
# 'publication_names', ...) from PostgreSQL 16.15 for:
#   CREATE TABLE ref_t (id int primary key, note text, big text);  -- big: STORAGE EXTERNAL
#   CREATE TABLE other_t (id int);
#   BEGIN; INSERT INTO ref_t VALUES (1, NULL, 'yy'); INSERT INTO other_t VALUES (7);
#          INSERT INTO ref_t VALUES (2, 'two', NULL); COMMIT;
#   UPDATE ref_t SET note = 'upd' WHERE id = 3;  -- big is an unchanged TOAST value
#   DELETE FROM ref_t WHERE id = 2;  TRUNCATE ref_t;
REAL = {
    "begin": "42000000000155421800030344868e0eb5000002ec",
    "relation": (
        "52000040437075626c6963007265665f74006400030169640000000017ffffffff"
        "006e6f74650000000019ffffffff006269670000000019ffffffff"
    ),
    "insert_1": "49000040434e00037400000001316e74000000027979",
    "relation_other": "520000404a7075626c6963006f746865725f74006400010069640000000017ffffffff",
    "insert_other": "490000404a4e0001740000000137",
    "insert_2": "49000040434e0003740000000132740000000374776f6e",
    "commit": "43000000000001554218000000000155424800030344868e0eb5",
    "update": "55000040434e0003740000000133740000000375706475",
    "delete": "44000040434b00037400000001326e6e",
    "truncate": "54000000010000004043",
}


def real(name: str) -> bytes:
    return bytes.fromhex(REAL[name])


class TestRealServerBytes:
    def test_transaction(self):
        decoder = PgOutputDecoder()
        begin = decoder.decode(real("begin"))
        assert isinstance(begin, Begin)
        assert begin.xid == 0x2EC
        assert begin.final_lsn == 0x1554218
        assert begin.commit_time.year == 2026

        rel = decoder.decode(real("relation"))
        assert isinstance(rel, Relation)
        assert (rel.relation_id, rel.qualified_name, rel.replica_identity) == (
            0x4043,
            "public.ref_t",
            "d",
        )
        assert [(c.name, c.type_oid, c.flags) for c in rel.columns] == [
            ("id", 23, 1),
            ("note", 25, 0),
            ("big", 25, 0),
        ]

        first = decoder.decode(real("insert_1"))
        assert isinstance(first, Insert)
        assert decoder.row(first) == {"id": "1", "note": None, "big": "yy"}

        other_rel = decoder.decode(real("relation_other"))
        assert isinstance(other_rel, Relation)
        assert other_rel.name == "other_t"
        other = decoder.decode(real("insert_other"))
        assert isinstance(other, Insert)
        assert decoder.row(other) == {"id": "7"}

        second = decoder.decode(real("insert_2"))
        assert isinstance(second, Insert)
        assert decoder.row(second) == {"id": "2", "note": "two", "big": None}

        commit = decoder.decode(real("commit"))
        assert isinstance(commit, Commit)
        assert commit.commit_lsn == begin.final_lsn
        assert commit.end_lsn == 0x1554248
        assert commit.commit_time == begin.commit_time
        assert set(decoder.relations) == {0x4043, 0x404A}

    @pytest.mark.parametrize(
        ("name", "kind"), [("update", "update"), ("delete", "delete"), ("truncate", "truncate")]
    )
    def test_other_changes_are_skipped(self, name, kind):
        assert decode_message(real(name)) == Skipped(kind)


class TestHandBuilt:
    def test_begin_and_commit(self):
        begin = decode_message(enc.begin(0x10, T0, xid=99))
        assert begin == Begin(final_lsn=0x10, commit_time=T0, xid=99)
        commit = decode_message(enc.commit(0x10, 0x48, T0, flags=0))
        assert commit == Commit(flags=0, commit_lsn=0x10, end_lsn=0x48, commit_time=T0)

    def test_large_lsn_and_xid(self):
        begin = decode_message(enc.begin(2**63 + 5, T0, xid=2**32 - 1))
        assert isinstance(begin, Begin)
        assert begin.final_lsn == 2**63 + 5
        assert begin.xid == 2**32 - 1

    def test_relation_in_pg_catalog(self):
        rel = decode_message(enc.relation(7, "", "pg_thing", [("a", 25)], identity="f"))
        assert isinstance(rel, Relation)
        assert rel.namespace == "pg_catalog"
        assert rel.replica_identity == "f"

    def test_multi_row_transaction(self):
        decoder = PgOutputDecoder()
        messages = [
            enc.begin(0x100, T0),
            enc.outbox_relation(42),
            enc.insert(42, enc.outbox_values(saga_id="a")),
            enc.insert(42, enc.outbox_values(saga_id="b", routing_key="rk")),
            enc.insert(42, enc.outbox_values(saga_id="c", tenant_id="acme")),
            enc.commit(0x100, 0x180, T0),
        ]
        decoded = [decoder.decode(m) for m in messages]
        rows = [decoder.row(m) for m in decoded if isinstance(m, Insert)]
        assert [r["saga_id"] for r in rows] == ["a", "b", "c"]
        assert rows[0]["routing_key"] is None
        assert rows[1]["routing_key"] == "rk"
        assert rows[2]["tenant_id"] == "acme"

    def test_nulls_unchanged_toast_and_binary(self):
        decoder = PgOutputDecoder()
        decoder.decode(enc.relation(1, "s", "t", [("a", 25), ("b", 25), ("c", 25), ("d", 17)]))
        message = enc.insert(1, [None, UNCHANGED_TOAST, "é", None])
        # Replace the last column with a binary datum ('b' kind).
        message = message[:-1] + b"b" + b"\x00\x00\x00\x02\x01\x02"
        insert = decoder.decode(message)
        assert isinstance(insert, Insert)
        assert insert.values == (None, UNCHANGED_TOAST, "é", b"\x01\x02")
        assert decoder.row(insert) == {"a": None, "c": "é", "d": b"\x01\x02"}

    def test_relation_is_replaced_on_schema_change(self):
        decoder = PgOutputDecoder()
        decoder.decode(enc.relation(1, "public", "t", [("a", 25)]))
        decoder.decode(enc.relation(1, "public", "t", [("a", 25), ("b", 25)]))
        insert = decoder.decode(enc.insert(1, ["x", "y"]))
        assert isinstance(insert, Insert)
        assert decoder.row(insert) == {"a": "x", "b": "y"}

    @pytest.mark.parametrize(
        ("message", "kind"),
        [
            (enc.update(1, ["x"]), "update"),
            (enc.update(1, ["x"], old=["w"]), "update"),
            (enc.delete(1, ["x"]), "delete"),
            (enc.truncate([1, 2]), "truncate"),
            (b"O" + b"\x00" * 8 + b"origin\x00", "origin"),
            (b"Y\x00\x00\x00\x01public\x00mytype\x00", "type"),
            (b"M\x00", "message"),
            (b"Z123", "unknown:Z"),
        ],
    )
    def test_skipped_messages(self, message, kind):
        assert decode_message(message) == Skipped(kind)


class TestMalformed:
    @pytest.mark.parametrize(
        "message",
        [
            b"",
            b"B\x00\x01",
            enc.commit(1, 2, T0)[:-3],
            b"R\x00\x00\x00\x01public",  # unterminated string
            b"I\x00\x00\x00\x01X\x00\x00",  # not a new tuple
            b"I\x00\x00\x00\x01N\x00\x01x",  # unknown column kind
            b"I\x00\x00\x00\x01N\x00\x01t\x00\x00\x00\x09abc",  # value shorter than its length
        ],
    )
    def test_raises_pgoutput_error(self, message):
        with pytest.raises(PgOutputError):
            decode_message(message)
        assert issubclass(PgOutputError, CDCError)

    def test_insert_before_relation(self):
        decoder = PgOutputDecoder()
        insert = decoder.decode(enc.insert(5, ["x"]))
        assert isinstance(insert, Insert)
        with pytest.raises(PgOutputError, match="before its Relation"):
            decoder.row(insert)

    def test_column_count_mismatch(self):
        decoder = PgOutputDecoder()
        decoder.decode(enc.relation(1, "public", "t", [("a", 25)]))
        insert = decoder.decode(enc.insert(1, ["x", "y"]))
        assert isinstance(insert, Insert)
        with pytest.raises(PgOutputError, match="2 values for 1 columns"):
            decoder.row(insert)


def test_helpers():
    assert pg_timestamp(0) == datetime(2000, 1, 1, tzinfo=UTC)
    assert pg_timestamp(enc.micros(T0)) == T0
    assert format_lsn(0x1_016B3748) == "1/16B3748"
    assert repr(UNCHANGED_TOAST) == "UNCHANGED_TOAST"
