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

try:
    import aioboto3  # exposed for test patching (sagaz.core.context.aioboto3)
except ImportError:
    aioboto3 = None  # type: ignore[assignment]

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
