"""SagaVersionRegistry — version store, optionally persisted to saga storage (ADR-018).

Registrations live in memory. Given a :class:`~sagaz.core.storage.SagaStorage`,
:meth:`SagaVersionRegistry.save` writes them as records under the reserved
saga name :data:`VERSION_RECORD_SAGA_NAME` and :meth:`SagaVersionRegistry.load`
reads them back, so registrations survive restarts and move with
``sagaz migrate`` like any other saga record.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Any

from sagaz.core.types import SagaStatus
from sagaz.versioning.exceptions import (
    SagaVersionNotFoundError,
    VersionAlreadyRegisteredError,
)
from sagaz.versioning.saga_version import SagaVersion
from sagaz.versioning.version import Version

#: Saga name under which version registrations are stored in saga storage.
VERSION_RECORD_SAGA_NAME = "__sagaz_versions__"

_MODEL_SCHEMA_PREFIX = "model:"


def _record_id(saga_version: SagaVersion) -> str:
    return f"{VERSION_RECORD_SAGA_NAME}:{saga_version.saga_name}:{saga_version.version}"


def _dump_schema(schema: Any) -> Any:
    """Dict schemas are stored as-is; model classes by their import path."""
    if isinstance(schema, dict):
        return dict(schema)
    return f"{_MODEL_SCHEMA_PREFIX}{schema.__module__}:{schema.__qualname__}"


def _load_schema(raw: Any) -> Any:
    if isinstance(raw, str) and raw.startswith(_MODEL_SCHEMA_PREFIX):
        module_name, _, qualname = raw.removeprefix(_MODEL_SCHEMA_PREFIX).partition(":")
        target: Any = importlib.import_module(module_name)
        for part in qualname.split("."):
            target = getattr(target, part)
        return target
    return dict(raw or {})


def _to_record(saga_version: SagaVersion) -> dict[str, Any]:
    deprecated = saga_version.deprecated_at
    return {
        "saga_name": saga_version.saga_name,
        "version": str(saga_version.version),
        "step_names": list(saga_version.step_names),
        "schema": _dump_schema(saga_version.schema),
        "deprecated_at": deprecated.isoformat() if deprecated else None,
    }


def _from_record(record: dict[str, Any]) -> SagaVersion:
    deprecated = record.get("deprecated_at")
    return SagaVersion(
        saga_name=record["saga_name"],
        version=Version.parse(record["version"]),
        step_names=list(record.get("step_names") or []),
        schema=_load_schema(record.get("schema")),
        deprecated_at=datetime.fromisoformat(deprecated) if deprecated else None,
    )


class SagaVersionRegistry:
    """
    Registry for saga version metadata.

    Stores :class:`SagaVersion` records keyed by ``(saga_name, version)``
    and supports lookup, listing, deprecation, and latest-version resolution.
    Pass a saga ``storage`` to persist registrations with :meth:`save` and
    restore them with :meth:`load` (or :meth:`from_storage`).
    """

    def __init__(self, storage: Any | None = None) -> None:
        # { saga_name: { Version: SagaVersion } }
        self._store: dict[str, dict[Version, SagaVersion]] = {}
        self._storage = storage

    # ── persistence ──

    @classmethod
    async def from_storage(cls, storage: Any) -> SagaVersionRegistry:
        """Create a registry bound to ``storage`` and load its registrations."""
        registry = cls(storage)
        await registry.load()
        return registry

    def _require_storage(self) -> Any:
        if self._storage is None:
            msg = "This registry has no storage: SagaVersionRegistry(storage=...)"
            raise ValueError(msg)
        return self._storage

    async def save(self) -> int:
        """Persist every registration (including deprecations); return how many."""
        storage = self._require_storage()
        saved = 0
        for versions in self._store.values():
            for saga_version in versions.values():
                await storage.save_saga_state(
                    _record_id(saga_version),
                    VERSION_RECORD_SAGA_NAME,
                    SagaStatus.COMPLETED,
                    [],
                    _to_record(saga_version),
                )
                saved += 1
        return saved

    async def load(self) -> int:
        """Replace in-memory registrations with the persisted ones; return how many."""
        storage = self._require_storage()
        summaries = await storage.list_sagas(saga_name=VERSION_RECORD_SAGA_NAME, limit=100_000)
        loaded: dict[str, dict[Version, SagaVersion]] = {}
        for summary in summaries:
            state = await storage.load_saga_state(summary["saga_id"])
            if not state:
                continue
            saga_version = _from_record(state["context"])
            loaded.setdefault(saga_version.saga_name, {})[saga_version.version] = saga_version
        self._store = loaded
        return sum(len(v) for v in loaded.values())

    # ── write ──

    def register(self, saga_version: SagaVersion) -> None:
        """
        Register a new saga version.

        Raises :class:`VersionAlreadyRegisteredError` if the same
        ``(saga_name, version)`` pair has already been registered.
        """
        name = saga_version.saga_name
        ver = saga_version.version
        if name not in self._store:
            self._store[name] = {}
        if ver in self._store[name]:
            raise VersionAlreadyRegisteredError(name, str(ver))
        self._store[name][ver] = saga_version

    def deprecate(self, saga_name: str, version: Version) -> None:
        """
        Mark a registered version as deprecated.

        Raises :class:`SagaVersionNotFoundError` if the version is unknown.
        """
        sv = self.get(saga_name, version)
        sv.deprecated_at = datetime.now(UTC)

    # ── read ──

    def get(self, saga_name: str, version: Version) -> SagaVersion:
        """
        Retrieve an exact saga version.

        Raises :class:`SagaVersionNotFoundError` when not found.
        """
        if saga_name not in self._store or version not in self._store[saga_name]:
            raise SagaVersionNotFoundError(saga_name, str(version))
        return self._store[saga_name][version]

    def get_latest(self, saga_name: str) -> SagaVersion:
        """
        Return the highest non-deprecated version for *saga_name*.

        Raises :class:`SagaVersionNotFoundError` when no active version exists.
        """
        active = [sv for sv in self._store.get(saga_name, {}).values() if not sv.is_deprecated]
        if not active:
            raise SagaVersionNotFoundError(saga_name, "latest")
        return max(active, key=lambda sv: sv.version)

    def list_versions(self, saga_name: str) -> list[SagaVersion]:
        """Return all registered versions (including deprecated) for *saga_name*."""
        return list(self._store.get(saga_name, {}).values())
