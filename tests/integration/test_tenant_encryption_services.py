"""Per-tenant encryption against real key services and PostgreSQL (ADR-020, phase 2).

- AWS KMS on LocalStack: data keys generated with the tenant encryption
  context; KMS itself refuses to unwrap one tenant's data key for another.
- Vault Transit in a dev-mode Vault container: one Transit key per tenant.
- PostgreSQL as an ordinary role: the stored rows contain no plaintext.
"""

from __future__ import annotations

import base64
import json
from uuid import uuid4

import pytest

from sagaz.core.tenant import TenantKeyError, tenant_scope
from sagaz.core.tenant.encryption import (
    AwsKmsKeyProvider,
    EncryptedSagaStorage,
    EnvKeyProvider,
    TenantCipher,
    VaultTransitKeyProvider,
    associated_data,
)
from sagaz.core.types import SagaStatus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SECRET = "123-45-6789"
AAD = associated_data("acme", "s1", "context")


# ── AWS KMS (LocalStack) ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def kms_endpoint(localstack_container):
    import boto3

    endpoint = localstack_container.get_url()
    kms = boto3.client(
        "kms",
        endpoint_url=endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    suffix = uuid4().hex[:8]
    for tenant in ("acme", "globex"):
        key_id = kms.create_key(Description=f"sagaz test {tenant}")["KeyMetadata"]["KeyId"]
        kms.create_alias(AliasName=f"alias/sagaz-{tenant}-{suffix}", TargetKeyId=key_id)
    return endpoint, suffix


def _kms_provider(kms_endpoint) -> AwsKmsKeyProvider:
    endpoint, suffix = kms_endpoint
    return AwsKmsKeyProvider(
        f"alias/sagaz-{{tenant_id}}-{suffix}",
        client_kwargs={
            "endpoint_url": endpoint,
            "region_name": "us-east-1",
            "aws_access_key_id": "test",
            "aws_secret_access_key": "test",
        },
    )


class TestAwsKms:
    async def test_round_trip_through_kms(self, kms_endpoint):
        sealed = await TenantCipher(_kms_provider(kms_endpoint)).encrypt("acme", {"x": 1}, AAD)
        fresh = TenantCipher(_kms_provider(kms_endpoint))  # forces a KMS Decrypt
        assert await fresh.decrypt("acme", sealed, AAD) == {"x": 1}

    async def test_kms_refuses_another_tenants_data_key(self, kms_endpoint):
        key = await _kms_provider(kms_endpoint).data_key("acme")
        with pytest.raises(TenantKeyError, match="KMS Decrypt"):
            await _kms_provider(kms_endpoint).resolve("globex", key.key_ref, key.wrapped)

    async def test_tenant_without_a_kms_key_fails_closed(self, kms_endpoint):
        with pytest.raises(TenantKeyError, match="GenerateDataKey"):
            await _kms_provider(kms_endpoint).data_key("initech")


# ── Vault Transit ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def vault_url():
    testcontainers = pytest.importorskip("testcontainers.core.container")
    from testcontainers.core.waiting_utils import wait_for_logs

    container = (
        testcontainers.DockerContainer("hashicorp/vault:1.17")
        .with_env("VAULT_DEV_ROOT_TOKEN_ID", "root")
        .with_env("SKIP_SETCAP", "true")
        .with_exposed_ports(8200)
    )
    try:
        container.start()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Vault container unavailable: {exc}")
    try:
        wait_for_logs(container, "Development mode should NOT be used", timeout=60)
        url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8200)}"
        import httpx

        headers = {"X-Vault-Token": "root"}
        httpx.post(f"{url}/v1/sys/mounts/transit", json={"type": "transit"}, headers=headers)
        for tenant in ("acme", "globex"):
            httpx.post(f"{url}/v1/transit/keys/sagaz-{tenant}", headers=headers).raise_for_status()
        yield url
    finally:
        container.stop()


class TestVaultTransit:
    async def test_round_trip_through_vault(self, vault_url):
        sealed = await TenantCipher(VaultTransitKeyProvider(vault_url, "root")).encrypt(
            "acme", {"x": 1}, AAD
        )
        assert sealed["__sagaz_encrypted__"]["edk"].startswith("vault:v1:")
        fresh = TenantCipher(VaultTransitKeyProvider(vault_url, "root"))
        assert await fresh.decrypt("acme", sealed, AAD) == {"x": 1}

    async def test_vault_refuses_a_data_key_under_another_tenants_key(self, vault_url):
        acme = await VaultTransitKeyProvider(vault_url, "root").data_key("acme")
        provider = VaultTransitKeyProvider(vault_url, "root")
        # Even naming globex's own key, acme's wrapped key does not decrypt.
        with pytest.raises(TenantKeyError, match="Vault request"):
            await provider.resolve("globex", "sagaz-globex", acme.wrapped)

    async def test_tenant_without_a_transit_key_fails_closed(self, vault_url):
        with pytest.raises(TenantKeyError, match="Vault request"):
            await VaultTransitKeyProvider(vault_url, "root").data_key("initech")


# ── PostgreSQL at rest ──────────────────────────────────────────────────────


async def test_postgresql_rows_hold_no_plaintext(app_role_url):
    asyncpg = pytest.importorskip("asyncpg")
    from sagaz.core.storage.backends.postgresql.saga import PostgreSQLSagaStorage

    keys = {"SAGAZ_TENANT_MASTER_KEY": base64.b64encode(b"m" * 32).decode()}
    steps = [{"name": "charge", "status": "completed", "result": {"card": SECRET}}]
    async with PostgreSQLSagaStorage(app_role_url, pool_min_size=1, pool_max_size=2) as inner:
        storage = EncryptedSagaStorage(inner, EnvKeyProvider(keys))
        with tenant_scope("acme"):
            await storage.save_saga_state(
                "s1", "PatientSaga", SagaStatus.COMPLETED, steps, {"ssn": SECRET}
            )
            assert (await storage.load_saga_state("s1"))["context"] == {"ssn": SECRET}

    conn = await asyncpg.connect(app_role_url)
    try:
        await conn.execute("SELECT set_config('app.tenant_id', 'acme', false)")
        rows = await conn.fetch("SELECT context::text FROM sagas")
        steps_rows = await conn.fetch("SELECT result::text FROM saga_steps")
    finally:
        await conn.close()
    dumped = json.dumps([tuple(r) for r in [*rows, *steps_rows]])
    assert rows
    assert steps_rows
    assert SECRET not in dumped
    assert "__sagaz_encrypted__" in dumped
