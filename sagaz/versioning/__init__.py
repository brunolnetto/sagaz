"""
Saga Versioning & Schema Evolution (ADR-018).

Provides semantic versioning, a version registry, context migration, and
version resolution for zero-downtime saga schema evolution.
"""

from sagaz.versioning.exceptions import (
    MigrationPathNotFoundError,
    SagaVersionError,
    SagaVersionNotFoundError,
    SagaVersionSchemaError,
    VersionAlreadyRegisteredError,
)
from sagaz.versioning.migration import MigrationEngine
from sagaz.versioning.mixin import SagaVersionedMixin
from sagaz.versioning.registry import VERSION_RECORD_SAGA_NAME, SagaVersionRegistry
from sagaz.versioning.resolver import SagaVersionResolver
from sagaz.versioning.saga_version import SagaVersion
from sagaz.versioning.validation import schema_violations, validate_context
from sagaz.versioning.version import Version

__all__ = [
    "VERSION_RECORD_SAGA_NAME",
    "MigrationEngine",
    "MigrationPathNotFoundError",
    "SagaVersion",
    "SagaVersionError",
    "SagaVersionNotFoundError",
    "SagaVersionRegistry",
    "SagaVersionResolver",
    "SagaVersionSchemaError",
    "SagaVersionedMixin",
    "Version",
    "VersionAlreadyRegisteredError",
    "schema_violations",
    "validate_context",
]
