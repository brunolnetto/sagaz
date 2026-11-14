"""Saga storage that encrypts each tenant's saga data at rest (ADR-020, phase 2)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sagaz.core.storage._reserved import is_reserved_saga_name
from sagaz.core.storage._tenancy import TENANT_FIELD, write_tenant
from sagaz.core.storage.interfaces.saga import SagaStorage
from sagaz.core.tenant._scope import current_tenant_id, is_system_scope
from sagaz.core.tenant.encryption._cipher import TenantCipher, associated_data, is_encrypted
from sagaz.core.tenant.encryption._keys import KeyProvider
from sagaz.core.types import SagaStatus, SagaStepStatus

CONTEXT_FIELD = "context"


def _step_field(step_name: str) -> str:
    return f"step:{step_name}"


class EncryptedSagaStorage(SagaStorage):
    """Wraps any :class:`SagaStorage` and encrypts saga context and step results.

    Each tenant's data is encrypted with that tenant's key (AES-256-GCM, see
    :class:`TenantCipher`). What stays in plaintext: saga ids and names,
    status, step names, statuses, errors and timestamps, which listing,
    statistics and cleanup need, and sagaz's own ``__sagaz_*`` records.

    Records written before encryption was enabled are read as they are, and
    are encrypted the next time they are saved. Exports carry the ciphertext,
    so a transfer to another backend keeps the data encrypted (the target
    needs the same keys); importing a plaintext record encrypts it.
    """

    def __init__(self, inner: SagaStorage, provider: KeyProvider | TenantCipher) -> None:
        self.inner = inner
        self.cipher = provider if isinstance(provider, TenantCipher) else TenantCipher(provider)

    def __getattr__(self, name: str) -> Any:
        # Backend-specific API (initialize, pools, ...) of the wrapped storage.
        return getattr(self.inner, name)

    # ── encryption of records ──

    async def _seal(self, tenant: str, saga_id: str, field: str, value: Any) -> Any:
        if value is None or is_encrypted(value):
            return value
        return await self.cipher.encrypt(tenant, value, associated_data(tenant, saga_id, field))

    async def _open(self, tenant: str, saga_id: str, field: str, value: Any) -> Any:
        return await self.cipher.decrypt(tenant, value, associated_data(tenant, saga_id, field))

    async def _seal_steps(self, tenant: str, saga_id: str, steps: list[dict[str, Any]]) -> list:
        sealed = []
        for step in steps:
            result = await self._seal(
                tenant, saga_id, _step_field(step["name"]), step.get("result")
            )
            sealed.append({**step, "result": result} if "result" in step else step)
        return sealed

    async def _open_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if is_reserved_saga_name(record.get("saga_name")):
            return record
        tenant = record.get(TENANT_FIELD) or current_tenant_id()
        saga_id = record["saga_id"]
        opened = dict(record)
        opened[CONTEXT_FIELD] = await self._open(
            tenant, saga_id, CONTEXT_FIELD, record.get(CONTEXT_FIELD)
        )
        steps = []
        for step in record.get("steps") or []:
            if step.get("result") is not None:
                field = _step_field(step["name"])
                step = {**step, "result": await self._open(tenant, saga_id, field, step["result"])}
            steps.append(step)
        if "steps" in record:
            opened["steps"] = steps
        return opened

    async def _seal_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if is_reserved_saga_name(record.get("saga_name")):
            return record
        tenant = write_tenant(record.get(TENANT_FIELD))
        saga_id = record["saga_id"]
        sealed = dict(record)
        sealed[CONTEXT_FIELD] = await self._seal(
            tenant, saga_id, CONTEXT_FIELD, record.get(CONTEXT_FIELD)
        )
        if record.get("steps"):
            sealed["steps"] = await self._seal_steps(tenant, saga_id, record["steps"])
        return sealed

    # ── SagaStorage ──

    async def save_saga_state(
        self,
        saga_id: str,
        saga_name: str,
        status: SagaStatus,
        steps: list[dict[str, Any]],
        context: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        configuration: list[str] | None = None,
    ) -> None:
        if not is_reserved_saga_name(saga_name):
            tenant = write_tenant()
            context = await self._seal(tenant, saga_id, CONTEXT_FIELD, context)
            steps = await self._seal_steps(tenant, saga_id, steps)
        await self.inner.save_saga_state(
            saga_id, saga_name, status, steps, context, metadata, configuration
        )

    async def load_saga_state(self, saga_id: str) -> dict[str, Any] | None:
        record = await self.inner.load_saga_state(saga_id)
        return await self._open_record(record) if record else record

    async def update_step_state(
        self,
        saga_id: str,
        step_name: str,
        status: SagaStepStatus,
        result: Any = None,
        error: str | None = None,
        executed_at: datetime | None = None,
    ) -> None:
        if result is not None and not is_system_scope():
            tenant = current_tenant_id()
            result = await self._seal(tenant, saga_id, _step_field(step_name), result)
        elif result is not None:
            # A step result written in the system scope could belong to any
            # tenant that has this saga id; refuse rather than guess its key.
            msg = "update_step_state with a result needs a tenant scope when encrypting"
            raise RuntimeError(msg)
        await self.inner.update_step_state(saga_id, step_name, status, result, error, executed_at)

    async def delete_saga_state(self, saga_id: str) -> bool:
        return await self.inner.delete_saga_state(saga_id)

    async def list_sagas(
        self,
        status: SagaStatus | None = None,
        saga_name: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        # Summaries carry no context or step results.
        return await self.inner.list_sagas(status, saga_name, limit, offset)

    async def get_saga_statistics(self) -> dict[str, Any]:
        return await self.inner.get_saga_statistics()

    async def cleanup_completed_sagas(
        self, older_than: datetime, statuses: list[SagaStatus] | None = None
    ) -> int:
        return await self.inner.cleanup_completed_sagas(older_than, statuses)

    async def health_check(self) -> dict[str, Any]:
        return await self.inner.health_check()

    async def export_all(self) -> AsyncIterator[dict[str, Any]]:
        async for record in self.inner.export_all():
            yield record

    async def import_record(self, record: dict[str, Any]) -> None:
        await self.inner.import_record(await self._seal_record(record))

    async def count(self) -> int:
        return await self.inner.count()

    async def __aenter__(self) -> EncryptedSagaStorage:
        await self.inner.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.inner.__aexit__(exc_type, exc_val, exc_tb)

    async def close(self) -> None:
        await self.inner.close()
