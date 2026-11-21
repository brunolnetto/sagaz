"""External storage signs what it pickles and loads nothing it cannot verify (#589)."""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sagaz.core.context import ExternalStorageIntegrityError, FileSystemExternalStorage
from sagaz.core.context._signing import KEY_ENV, resolve_key, seal, unseal

KEY = "a-test-signing-key-of-32-bytes!!"


class Exploit:
    """Unpickling this runs code: what a tampered payload would carry."""

    def __reduce__(self):
        return (Path("pwned").touch, ())


def storage(tmp_path: Path, **kwargs) -> FileSystemExternalStorage:
    return FileSystemExternalStorage(str(tmp_path / "store"), **({"signing_key": KEY} | kwargs))


def path_of(uri: str) -> Path:
    return Path(uri.removeprefix("file://"))


class TestKeys:
    def test_a_key_is_required(self, tmp_path, monkeypatch):
        monkeypatch.delenv(KEY_ENV, raising=False)
        with pytest.raises(ValueError, match=KEY_ENV):
            FileSystemExternalStorage(str(tmp_path))

    def test_the_key_can_come_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv(KEY_ENV, KEY)
        assert FileSystemExternalStorage(str(tmp_path))._key == KEY.encode()

    def test_a_short_key_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="at least 16 bytes"):
            FileSystemExternalStorage(str(tmp_path), signing_key="short")

    def test_bytes_and_str_keys_are_the_same_key(self):
        assert resolve_key(KEY) == resolve_key(KEY.encode())


class TestRoundTrip:
    async def test_a_value_round_trips(self, tmp_path):
        store = storage(tmp_path)
        ref = await store.store("saga-1", "payload", {"rows": [1, 2, 3]})
        assert await store.load(ref.uri) == {"rows": [1, 2, 3]}
        assert ref.size_bytes == len(pickle.dumps({"rows": [1, 2, 3]}))

    async def test_another_process_with_the_same_key_loads_it(self, tmp_path):
        ref = await storage(tmp_path).store("saga-1", "payload", [1])
        assert await storage(tmp_path).load(ref.uri) == [1]


class TestTampering:
    async def test_a_replaced_payload_is_not_unpickled(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        store = storage(tmp_path)
        ref = await store.store("saga-1", "payload", "fine")
        path_of(ref.uri).write_bytes(pickle.dumps(Exploit()))  # an attacker's unsigned pickle
        with pytest.raises(ExternalStorageIntegrityError, match="not signed"):
            await store.load(ref.uri)
        assert not (tmp_path / "pwned").exists()

    async def test_a_modified_payload_fails_verification(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        store = storage(tmp_path)
        ref = await store.store("saga-1", "payload", "fine")
        blob = path_of(ref.uri).read_bytes()
        path_of(ref.uri).write_bytes(blob[:36] + pickle.dumps(Exploit()))  # keep the old tag
        with pytest.raises(ExternalStorageIntegrityError, match="signature verification"):
            await store.load(ref.uri)
        assert not (tmp_path / "pwned").exists()

    async def test_another_key_cannot_load_it(self, tmp_path):
        ref = await storage(tmp_path).store("saga-1", "payload", "fine")
        other = storage(tmp_path, signing_key="another-key-0123456789")
        with pytest.raises(ExternalStorageIntegrityError):
            await other.load(ref.uri)

    async def test_a_payload_moved_to_another_name_fails(self, tmp_path):
        store = storage(tmp_path)
        a = await store.store("saga-1", "a", "for saga 1")
        b = await store.store("saga-2", "b", "for saga 2")
        path_of(b.uri).write_bytes(path_of(a.uri).read_bytes())
        with pytest.raises(ExternalStorageIntegrityError):
            await store.load(b.uri)


class TestUnsignedPayloads:
    async def test_allow_unsigned_reads_a_legacy_payload_with_a_warning(self, tmp_path, caplog):
        store = storage(tmp_path, allow_unsigned=True)
        legacy = store.base_path / "saga-old" / "payload.bin"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(pickle.dumps({"old": True}))
        with caplog.at_level(logging.WARNING):
            assert await store.load(f"file://{legacy.resolve()}") == {"old": True}
        assert "unsigned" in caplog.text

    async def test_allow_unsigned_still_checks_signed_payloads(self, tmp_path):
        store = storage(tmp_path, allow_unsigned=True)
        ref = await store.store("saga-1", "payload", "fine")
        blob = path_of(ref.uri).read_bytes()
        path_of(ref.uri).write_bytes(blob[:-1] + b"X")
        with pytest.raises(ExternalStorageIntegrityError):
            await store.load(ref.uri)


class TestConfinement:
    async def test_load_refuses_a_file_outside_the_storage(self, tmp_path):
        outside = tmp_path / "elsewhere.bin"
        outside.write_bytes(b"whatever")
        with pytest.raises(ValueError, match="outside the storage directory"):
            await storage(tmp_path).load(f"file://{outside}")

    async def test_load_refuses_a_path_that_climbs_out(self, tmp_path):
        store = storage(tmp_path)
        with pytest.raises(ValueError, match="outside the storage directory"):
            await store.load(f"file://{store.base_path}/../elsewhere.bin")

    async def test_delete_leaves_files_outside_the_storage_alone(self, tmp_path):
        outside = tmp_path / "keep.txt"
        outside.write_text("keep me")
        await storage(tmp_path).delete(f"file://{outside}")
        assert outside.exists()

    async def test_a_key_cannot_store_outside_the_storage(self, tmp_path):
        with pytest.raises(ValueError, match="outside"):
            await storage(tmp_path).store("saga-1", "../../escaped", "value")


class TestSealing:
    def test_unseal_returns_what_seal_wrapped(self):
        key = resolve_key(KEY)
        assert unseal(key, "n", seal(key, "n", b"data")) == b"data"

    def test_the_name_is_part_of_the_signature(self):
        key = resolve_key(KEY)
        with pytest.raises(ExternalStorageIntegrityError):
            unseal(key, "other", seal(key, "n", b"data"))


class TestS3:
    async def test_a_tampered_object_is_not_unpickled(self):
        client = MagicMock()
        body = AsyncMock()
        body.read.return_value = pickle.dumps(Exploit())
        body.__aenter__.return_value = body
        client.get_object = AsyncMock(return_value={"Body": body})
        session = MagicMock()
        session.client.return_value.__aenter__.return_value = client
        with (
            patch("sagaz.core.context._storage.HAS_AIOBOTO3", True),
            patch("sagaz.core.context._storage._aioboto3") as aioboto3,
        ):
            aioboto3.return_value.Session.return_value = session
            from sagaz.core.context import S3ExternalStorage

            s3 = S3ExternalStorage("bucket", signing_key=KEY)
            with pytest.raises(ExternalStorageIntegrityError):
                await s3.load("s3://bucket/saga-1/payload.bin")
