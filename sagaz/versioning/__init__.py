"""
Saga Versioning & Schema Evolution (ADR-018).

Provides semantic versioning, a version registry, context migration, and
version resolution for zero-downtime saga schema evolution.
"""

from sagaz.versioning.exceptions import (
    MigrationPathNotFoundError,
    SagaVersionError,
    SagaVersionNotFoundError,
    VersionAlreadyRegisteredError,
)
from sagaz.versioning.migration import MigrationEngine
from sagaz.versioning.registry import SagaVersionRegistry
from sagaz.versioning.resolver import SagaVersionResolver
from sagaz.versioning.saga_version import SagaVersion
from sagaz.versioning.version import Version

__all__ = [
    "MigrationEngine",
    "MigrationPathNotFoundError",
    "SagaVersion",
    "SagaVersionError",
    "SagaVersionNotFoundError",
    "SagaVersionRegistry",
    "SagaVersionResolver",
    "Version",
    "VersionAlreadyRegisteredError",
]
