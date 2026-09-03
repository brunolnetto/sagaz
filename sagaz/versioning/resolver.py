"""SagaVersionResolver — pick the right saga version to execute (ADR-018)."""

from __future__ import annotations

from sagaz.versioning.registry import SagaVersionRegistry
from sagaz.versioning.saga_version import SagaVersion
from sagaz.versioning.version import Version


class SagaVersionResolver:
    """
    Decide which :class:`SagaVersion` to use for a given execution request.

    Rules:
    - **New saga** (``saga_id=None``, no ``pinned_version``): use the latest
      non-deprecated version from the registry.
    - **Resuming saga** (``pinned_version`` provided): use the exact pinned
      version, preserving the version that was originally started.

    Parameters
    ----------
    registry:
        Populated :class:`SagaVersionRegistry` instance.
    """

    def __init__(self, registry: SagaVersionRegistry) -> None:
        self._registry = registry

    def resolve(
        self,
        saga_name: str,
        saga_id: str | None,
        pinned_version: str | None = None,
    ) -> SagaVersion:
        """
        Resolve the appropriate saga version.

        Parameters
        ----------
        saga_name:
            Logical saga identifier.
        saga_id:
            ID of an existing saga being resumed, or ``None`` for new sagas.
        pinned_version:
            Explicit version string to force.  Required when resuming an
            existing saga and authoritative whenever provided.

        Returns
        -------
        SagaVersion
            The resolved saga version record.

        Raises
        ------
        ValueError
            If ``saga_id`` is provided without a corresponding
            ``pinned_version``.
        """
        if pinned_version is not None:
            return self._registry.get(saga_name, Version.parse(pinned_version))
        if saga_id is not None:
            msg = "pinned_version is required when resolving a resumed saga"
            raise ValueError(msg)
        return self._registry.get_latest(saga_name)
