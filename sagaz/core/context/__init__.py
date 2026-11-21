"""
Saga Context Management

Enhanced context with support for:
1. External storage for large payloads (Reference-based)
2. Streaming support via AsyncGenerators
3. Warning-based memory footprint validation
4. Optional automatic offloading (requires external storage)
"""

from sagaz.core.context._context import (
    ConfigurationError,
    LargePayloadWarning,
    MemoryFootprintError,
    SagaContext,
)
from sagaz.core.context._storage import (
    HAS_AIOBOTO3,
    ExternalReference,
    ExternalStorage,
    FileSystemExternalStorage,
    S3ExternalStorage,
)


def __getattr__(name: str) -> object:
    """``sagaz.core.context.aioboto3``, imported on first access (it is slow to import)."""
    if name == "aioboto3":
        from sagaz.core.context._storage import _aioboto3

        return _aioboto3()
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "HAS_AIOBOTO3",
    "ConfigurationError",
    "ExternalReference",
    "ExternalStorage",
    "FileSystemExternalStorage",
    "LargePayloadWarning",
    "MemoryFootprintError",
    "S3ExternalStorage",
    "SagaContext",
]
