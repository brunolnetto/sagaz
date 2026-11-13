"""Exceptions for saga versioning (ADR-018)."""

from __future__ import annotations


class SagaVersionError(Exception):
    """Base exception for saga versioning errors."""


class SagaVersionNotFoundError(SagaVersionError):
    """Raised when a requested saga version is not registered."""

    def __init__(self, saga_name: str, version: str) -> None:
        self.saga_name = saga_name
        self.version = version
        msg = f"Saga version not found: '{saga_name}' v{version}"
        super().__init__(msg)


class VersionAlreadyRegisteredError(SagaVersionError):
    """Raised when the same (saga_name, version) is registered twice."""

    def __init__(self, saga_name: str, version: str) -> None:
        self.saga_name = saga_name
        self.version = version
        msg = f"Version already registered: '{saga_name}' v{version}"
        super().__init__(msg)


class MigrationPathNotFoundError(SagaVersionError):
    """Raised when no migration path exists between two versions."""

    def __init__(self, saga_name: str, from_version: str, to_version: str) -> None:
        self.saga_name = saga_name
        self.from_version = from_version
        self.to_version = to_version
        msg = f"No migration path for '{saga_name}': v{from_version} -> v{to_version}"
        super().__init__(msg)
