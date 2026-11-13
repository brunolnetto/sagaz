"""SagaVersionRegistry — in-memory version store (ADR-018)."""

from __future__ import annotations

from datetime import UTC, datetime

from sagaz.versioning.exceptions import (
    SagaVersionNotFoundError,
    VersionAlreadyRegisteredError,
)
from sagaz.versioning.saga_version import SagaVersion
from sagaz.versioning.version import Version


class SagaVersionRegistry:
    """
    In-memory registry for saga version metadata.

    Stores :class:`SagaVersion` records keyed by ``(saga_name, version)``
    and supports lookup, listing, deprecation, and latest-version resolution.
    """

    def __init__(self) -> None:
        # { saga_name: { Version: SagaVersion } }
        self._store: dict[str, dict[Version, SagaVersion]] = {}

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
