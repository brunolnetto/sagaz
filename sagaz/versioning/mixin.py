"""Versioned declarative sagas: resolve the active version and validate context (ADR-018)."""

from __future__ import annotations

from typing import Any, ClassVar

from sagaz.versioning.exceptions import SagaVersionError
from sagaz.versioning.registry import SagaVersionRegistry
from sagaz.versioning.saga_version import SagaVersion
from sagaz.versioning.validation import validate_context
from sagaz.versioning.version import Version


class SagaVersionedMixin:
    """Validate a saga's context against its registered version before it runs.

    Place it before :class:`sagaz.Saga`::

        class OrderSaga(SagaVersionedMixin, Saga):
            saga_name = "order"
            version_registry = registry   # a SagaVersionRegistry
            saga_version = "2.0.0"        # optional; default: latest active version

    ``run()`` resolves the version from ``version_registry`` (the pinned
    ``saga_version``, else the latest non-deprecated one) and raises
    :class:`~sagaz.versioning.exceptions.SagaVersionSchemaError` — before any
    step executes — when the initial context does not match that version's
    schema.
    """

    saga_version: ClassVar[str | None] = None
    version_registry: ClassVar[SagaVersionRegistry | None] = None

    def active_saga_version(self) -> SagaVersion:
        """The registered version this saga runs as."""
        registry = self.version_registry
        if registry is None:
            msg = f"{type(self).__name__} needs a version_registry to run as a versioned saga"
            raise SagaVersionError(msg)
        name = getattr(self, "saga_name", None) or type(self).__name__
        if self.saga_version:
            return registry.get(name, Version.parse(self.saga_version))
        return registry.get_latest(name)

    async def run(
        self, initial_context: dict[str, Any], saga_id: str | None = None
    ) -> dict[str, Any]:
        validate_context(self.active_saga_version(), initial_context)
        parent: Any = super()
        result: dict[str, Any] = await parent.run(initial_context, saga_id)
        return result
