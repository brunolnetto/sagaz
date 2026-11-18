"""Tenant key providers and the AES-256-GCM cipher (ADR-020, phase 2)."""

from __future__ import annotations

import base64
import json
import os

import httpx
import pytest

# Encryption needs the optional "cryptography" package (sagaz[encryption]).
pytest.importorskip("cryptography")

from sagaz.core.tenant import TenantDecryptionError, TenantKeyError  # noqa: E402
from sagaz.core.tenant.encryption import (  # noqa: E402
    ENVELOPE_FIELD,
    AwsKmsKeyProvider,
    CachingKeyProvider,
    DataKey,
    EnvKeyProvider,
    KeyProvider,
    TenantCipher,
    VaultTransitKeyProvider,
    associated_data,
    is_encrypted,
)


def _key(seed: int = 1) -> str:
    return base64.b64encode(bytes([seed]) * 32).decode()


AAD = associated_data("acme", "saga-1", "context")


class TestCipher:
    async def test_round_trip_and_no_plaintext_in_envelope(self):
        cipher = TenantCipher(EnvKeyProvider({"SAGAZ_TENANT_KEY_ACME": _key()}))
        value = {"ssn": "123-45-6789", "amount": 10}

        sealed = await cipher.encrypt("acme", value, AAD)

        assert is_encrypted(sealed)
        envelope = sealed[ENVELOPE_FIELD]
        assert (envelope["v"], envelope["alg"], envelope["key"]) == (1, "A256GCM", "env:1")
        assert "edk" not in envelope
        assert "123-45-6789" not in json.dumps(sealed)
        assert await cipher.decrypt("acme", sealed, AAD) == value

    async def test_each_encryption_uses_a_fresh_nonce(self):
        cipher = TenantCipher(EnvKeyProvider({"SAGAZ_TENANT_KEY_ACME": _key()}))
        a = await cipher.encrypt("acme", {"x": 1}, AAD)
        b = await cipher.encrypt("acme", {"x": 1}, AAD)
        assert a[ENVELOPE_FIELD]["nonce"] != b[ENVELOPE_FIELD]["nonce"]
        assert a[ENVELOPE_FIELD]["ct"] != b[ENVELOPE_FIELD]["ct"]

    @pytest.mark.parametrize(
        "other",
        [
            associated_data("globex", "saga-1", "context"),
            associated_data("acme", "saga-2", "context"),
            associated_data("acme", "saga-1", "step:charge"),
        ],
        ids=["other-tenant", "other-saga", "other-field"],
    )
    async def test_ciphertext_is_bound_to_tenant_saga_and_field(self, other):
        # Same key for both tenants, to show the binding does not rely on keys.
        env = {"SAGAZ_TENANT_KEY_ACME": _key(), "SAGAZ_TENANT_KEY_GLOBEX": _key()}
        cipher = TenantCipher(EnvKeyProvider(env))
        sealed = await cipher.encrypt("acme", {"x": 1}, AAD)
        with pytest.raises(TenantDecryptionError, match="authentication failed"):
            await cipher.decrypt("globex" if b"globex" in other else "acme", sealed, other)

    async def test_tampered_ciphertext_is_rejected(self):
        cipher = TenantCipher(EnvKeyProvider({"SAGAZ_TENANT_KEY_ACME": _key()}))
        sealed = await cipher.encrypt("acme", {"x": 1}, AAD)
        ct = bytearray(base64.b64decode(sealed[ENVELOPE_FIELD]["ct"]))
        ct[0] ^= 1
        sealed[ENVELOPE_FIELD]["ct"] = base64.b64encode(bytes(ct)).decode()
        with pytest.raises(TenantDecryptionError):
            await cipher.decrypt("acme", sealed, AAD)

    async def test_unknown_envelope_version_is_rejected(self):
        cipher = TenantCipher(EnvKeyProvider({"SAGAZ_TENANT_KEY_ACME": _key()}))
        sealed = await cipher.encrypt("acme", {"x": 1}, AAD)
        sealed[ENVELOPE_FIELD]["v"] = 99
        with pytest.raises(TenantDecryptionError, match="unsupported"):
            await cipher.decrypt("acme", sealed, AAD)

    @pytest.mark.parametrize("value", [None, {"plain": True}, [1, 2], "text"])
    async def test_plain_values_pass_through(self, value):
        cipher = TenantCipher(EnvKeyProvider({}))
        assert await cipher.decrypt("acme", value, AAD) == value

    async def test_values_must_be_json(self):
        cipher = TenantCipher(EnvKeyProvider({"SAGAZ_TENANT_KEY_ACME": _key()}))
        with pytest.raises(TypeError):
            await cipher.encrypt("acme", {"when": object()}, AAD)


class TestEnvKeyProvider:
    async def test_tenant_key_and_env_name(self):
        provider = EnvKeyProvider({"SAGAZ_TENANT_KEY_ACME_CORP_EU_1": f"k2:{_key(2)}"})
        key = await provider.data_key("acme-corp.eu_1")
        assert (key.key_ref, key.key, key.wrapped) == ("env:k2", bytes([2]) * 32, None)

    async def test_rotation_encrypts_with_the_first_and_decrypts_with_any(self):
        old = TenantCipher(EnvKeyProvider({"SAGAZ_TENANT_KEY_ACME": f"k1:{_key(1)}"}))
        sealed = await old.encrypt("acme", {"x": 1}, AAD)

        rotated = EnvKeyProvider({"SAGAZ_TENANT_KEY_ACME": f"k2:{_key(2)}, k1:{_key(1)}"})
        assert (await rotated.data_key("acme")).key_ref == "env:k2"
        assert await TenantCipher(rotated).decrypt("acme", sealed, AAD) == {"x": 1}

    async def test_master_key_derives_distinct_keys_per_tenant(self):
        provider = EnvKeyProvider({"SAGAZ_TENANT_MASTER_KEY": _key(7)})
        acme, globex = await provider.data_key("acme"), await provider.data_key("globex")
        assert acme.key_ref == globex.key_ref == "hkdf:1"
        assert acme.key != globex.key
        assert acme.key != bytes([7]) * 32
        assert await provider.resolve("acme", "hkdf:1", None) == acme.key

    async def test_own_key_takes_precedence_over_master(self):
        env = {"SAGAZ_TENANT_MASTER_KEY": _key(7), "SAGAZ_TENANT_KEY_ACME": _key(1)}
        assert (await EnvKeyProvider(env).data_key("acme")).key_ref == "env:1"

    async def test_missing_key_fails_closed(self):
        with pytest.raises(TenantKeyError, match="SAGAZ_TENANT_KEY_ACME"):
            await EnvKeyProvider({}).data_key("acme")

    @pytest.mark.parametrize(
        ("value", "message"),
        [
            ("not base64!", "not valid base64"),
            (base64.b64encode(b"short").decode(), "32 bytes"),
            (" , ", "empty"),
        ],
    )
    async def test_malformed_keys(self, value, message):
        with pytest.raises(TenantKeyError, match=message):
            await EnvKeyProvider({"SAGAZ_TENANT_KEY_ACME": value}).data_key("acme")

    async def test_resolve_rejects_unknown_or_foreign_references(self):
        provider = EnvKeyProvider({"SAGAZ_TENANT_KEY_ACME": _key()})
        with pytest.raises(TenantKeyError, match="not configured"):
            await provider.resolve("acme", "env:old", None)
        with pytest.raises(TenantKeyError, match="not configured"):
            await provider.resolve("acme", "hkdf:1", None)

    def test_defaults_to_the_process_environment(self, monkeypatch):
        monkeypatch.setenv("SAGAZ_TENANT_KEY_ACME", _key())
        assert EnvKeyProvider()._keys("acme")[0] == "env"

    def test_is_a_key_provider(self):
        assert isinstance(EnvKeyProvider({}), KeyProvider)

    def test_data_keys_must_be_256_bit(self):
        with pytest.raises(ValueError, match="32 bytes"):
            DataKey(b"short", "x")


class CountingProvider(CachingKeyProvider):
    def __init__(self, **options):
        super().__init__(**options)
        self.generated = 0
        self.unwrapped = 0

    async def _generate(self, tenant_id):
        self.generated += 1
        return DataKey(os.urandom(32), "k", f"wrapped-{tenant_id}-{self.generated}")

    async def _unwrap(self, tenant_id, key_ref, wrapped):
        self.unwrapped += 1
        return bytes([self.unwrapped]) * 32


class TestCachingKeyProvider:
    async def test_data_key_is_reused_until_max_uses(self):
        provider = CountingProvider(max_key_uses=2)
        first = await provider.data_key("acme")
        assert await provider.data_key("acme") is first
        assert await provider.data_key("acme") is not first
        assert provider.generated == 2

    async def test_data_key_expires_after_ttl(self, monkeypatch):
        from types import SimpleNamespace

        from sagaz.core.tenant.encryption import _keys

        clock = iter([0.0, 10.0, 1000.0])
        monkeypatch.setattr(_keys, "time", SimpleNamespace(monotonic=lambda: next(clock)))
        provider = CountingProvider(data_key_ttl=60)
        first = await provider.data_key("acme")
        assert await provider.data_key("acme") is first
        assert await provider.data_key("acme") is not first

    async def test_generated_keys_resolve_without_a_service_call(self):
        provider = CountingProvider()
        key = await provider.data_key("acme")
        assert await provider.resolve("acme", key.key_ref, key.wrapped) == key.key
        assert provider.unwrapped == 0

    async def test_unwrapped_keys_are_cached_lru(self):
        provider = CountingProvider(cache_size=2)
        await provider.resolve("acme", "k", "a")
        await provider.resolve("acme", "k", "b")
        await provider.resolve("acme", "k", "a")  # hit, now most recent
        await provider.resolve("acme", "k", "c")  # evicts "b"
        assert provider.unwrapped == 3
        await provider.resolve("acme", "k", "a")
        assert provider.unwrapped == 3
        await provider.resolve("acme", "k", "b")
        assert provider.unwrapped == 4


class FakeKms:
    """Stands in for an aioboto3 KMS client; enforces the encryption context."""

    def __init__(self):
        self.calls = []

    def client(self, service, **kwargs):
        assert service == "kms"
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def generate_data_key(self, KeyId, KeySpec, EncryptionContext):  # noqa: N803 (boto3 names)
        self.calls.append(("generate", KeyId, EncryptionContext))
        plaintext = os.urandom(32)
        blob = json.dumps(
            {"key": base64.b64encode(plaintext).decode(), "ctx": EncryptionContext, "id": KeyId}
        ).encode()
        return {"Plaintext": plaintext, "CiphertextBlob": blob}

    async def decrypt(self, CiphertextBlob, KeyId, EncryptionContext):  # noqa: N803
        self.calls.append(("decrypt", KeyId, EncryptionContext))
        blob = json.loads(CiphertextBlob)
        if blob["ctx"] != EncryptionContext:
            msg = "InvalidCiphertextException"
            raise RuntimeError(msg)
        return {"Plaintext": base64.b64decode(blob["key"])}


class TestAwsKmsKeyProvider:
    async def test_envelope_round_trip_with_tenant_encryption_context(self):
        kms = FakeKms()
        cipher = TenantCipher(AwsKmsKeyProvider(session=kms))
        sealed = await cipher.encrypt("acme", {"x": 1}, AAD)

        assert sealed[ENVELOPE_FIELD]["key"] == "alias/sagaz-acme"
        assert sealed[ENVELOPE_FIELD]["edk"]
        assert kms.calls == [("generate", "alias/sagaz-acme", {"sagaz:tenant": "acme"})]

        fresh = TenantCipher(AwsKmsKeyProvider(session=kms))  # empty cache
        assert await fresh.decrypt("acme", sealed, AAD) == {"x": 1}
        assert kms.calls[-1] == ("decrypt", "alias/sagaz-acme", {"sagaz:tenant": "acme"})

    async def test_kms_refuses_another_tenants_data_key(self):
        kms = FakeKms()
        provider = AwsKmsKeyProvider(session=kms)
        key = await provider.data_key("acme")
        with pytest.raises(TenantKeyError, match="KMS Decrypt"):
            await AwsKmsKeyProvider(session=kms).resolve("globex", key.key_ref, key.wrapped)

    async def test_key_id_callable_and_errors(self):
        provider = AwsKmsKeyProvider(lambda t: f"arn:aws:kms:key/{t}", session=FakeKms())
        assert provider.key_id_for("acme") == "arn:aws:kms:key/acme"
        with pytest.raises(TenantKeyError, match="no wrapped data key"):
            await provider.resolve("acme", "x", None)

        class Broken(FakeKms):
            async def generate_data_key(self, **kwargs):
                msg = "AccessDenied"
                raise RuntimeError(msg)

        with pytest.raises(TenantKeyError, match="GenerateDataKey.*AccessDenied"):
            await AwsKmsKeyProvider(session=Broken()).data_key("acme")


def _vault_transport(requests):
    """A fake Vault Transit API: datakey wraps as 'vault:v1:<key>:<b64>'."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-Vault-Token"] == "root"
        body = json.loads(request.content)
        path = request.url.path
        if path.startswith("/v1/transit/datakey/plaintext/"):
            key = os.urandom(32)
            name = path.rsplit("/", 1)[1]
            wrapped = f"vault:v1:{name}:{base64.b64encode(key).decode()}"
            data = {"plaintext": base64.b64encode(key).decode(), "ciphertext": wrapped}
            return httpx.Response(200, json={"data": data})
        if path.startswith("/v1/transit/decrypt/"):
            name = path.rsplit("/", 1)[1]
            _, _, owner, b64 = body["ciphertext"].split(":")
            if owner != name:
                return httpx.Response(
                    400, json={"errors": ["cipher: message authentication failed"]}
                )
            return httpx.Response(200, json={"data": {"plaintext": b64}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


class TestVaultTransitKeyProvider:
    async def test_envelope_round_trip(self):
        requests = []
        transport = _vault_transport(requests)
        provider = VaultTransitKeyProvider("http://vault:8200", "root", transport=transport)
        sealed = await TenantCipher(provider).encrypt("acme", {"x": 1}, AAD)

        envelope = sealed[ENVELOPE_FIELD]
        assert envelope["key"] == "sagaz-acme"
        assert envelope["edk"].startswith("vault:v1:")
        fresh = VaultTransitKeyProvider("http://vault:8200", "root", transport=transport)
        assert await TenantCipher(fresh).decrypt("acme", sealed, AAD) == {"x": 1}
        assert [r.url.path for r in requests] == [
            "/v1/transit/datakey/plaintext/sagaz-acme",
            "/v1/transit/decrypt/sagaz-acme",
        ]

    async def test_reference_to_another_tenants_key_is_refused_locally(self):
        provider = VaultTransitKeyProvider("http://v", "root", transport=_vault_transport([]))
        with pytest.raises(TenantKeyError, match="does not belong"):
            await provider.resolve("globex", "sagaz-acme", "vault:v1:sagaz-acme:xx")

    async def test_errors_and_configuration(self, monkeypatch):
        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        with pytest.raises(TenantKeyError, match="not configured"):
            await VaultTransitKeyProvider().data_key("acme")

        transport = httpx.MockTransport(lambda request: httpx.Response(403))
        provider = VaultTransitKeyProvider(
            "http://v", "root", namespace="team", mount="/kv-transit/", transport=transport
        )
        with pytest.raises(TenantKeyError, match="Vault request"):
            await provider.data_key("acme")
        with pytest.raises(TenantKeyError, match="no wrapped data key"):
            await provider.resolve("acme", "sagaz-acme", None)

        monkeypatch.setenv("VAULT_ADDR", "http://env-vault:8200/")
        monkeypatch.setenv("VAULT_TOKEN", "t")
        named = VaultTransitKeyProvider(key_name=lambda t: f"tenants/{t}")
        assert (named._url, named._token, named.key_name_for("acme")) == (
            "http://env-vault:8200",
            "t",
            "tenants/acme",
        )

    async def test_namespace_header_is_sent(self):
        seen = []

        def handler(request):
            seen.append(request.headers.get("X-Vault-Namespace"))
            key = base64.b64encode(os.urandom(32)).decode()
            return httpx.Response(200, json={"data": {"plaintext": key, "ciphertext": "c"}})

        provider = VaultTransitKeyProvider(
            "http://v", "root", namespace="team", transport=httpx.MockTransport(handler)
        )
        await provider.data_key("acme")
        assert seen == ["team"]


async def test_kms_provider_creates_an_aioboto3_session_lazily():
    pytest.importorskip("aioboto3")  # sagaz[aws]; not part of the dev group
    provider = AwsKmsKeyProvider(client_kwargs={"region_name": "us-east-1"})
    assert provider._session is None
    async with provider._client() as kms:  # building the client makes no request
        assert hasattr(kms, "generate_data_key")
    assert provider._session is not None
