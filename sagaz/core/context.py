# ============================================
# FILE: sagaz/core/context.py
# ============================================

"""
Saga Context Management

Enhanced context with support for:
1. External storage for large payloads (Reference-based)
2. Streaming support via AsyncGenerators
3. Automatic size estimation and offloading
"""

import hashlib
import pickle
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles

try:
    import aioboto3
    HAS_AIOBOTO3 = True
except ImportError:  # pragma: no cover
    HAS_AIOBOTO3 = False


@dataclass
class ExternalReference:
    """Reference to externally stored data"""

    uri: str  # Storage URI (s3://bucket/key, file:///path/to/file)
    size_bytes: int  # Original size
    content_type: str  # MIME type
    checksum: str  # SHA256 hash
    created_at: datetime
    ttl_seconds: int | None = None  # Auto-cleanup after TTL


class ExternalStorage(ABC):
    """Abstract base for external storage backends"""

    @abstractmethod
    async def store(
        self, saga_id: str, key: str, value: Any, ttl_seconds: int | None = None
    ) -> ExternalReference:
        """Store value and return reference"""
        ...

    @abstractmethod
    async def load(self, uri: str) -> Any:
        """Load value from URI"""
        ...

    @abstractmethod
    async def delete(self, uri: str) -> None:
        """Delete stored value"""
        ...


class FileSystemExternalStorage(ExternalStorage):
    """Local filesystem implementation for external storage"""

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def store(
        self, saga_id: str, key: str, value: Any, ttl_seconds: int | None = None
    ) -> ExternalReference:
        # Serialize
        data = pickle.dumps(value)

        # Create file path
        # Use a random UUID to avoid collisions for same key in same saga (e.g. loops)
        file_name = f"{key}-{uuid.uuid4()}.bin"
        saga_dir = self.base_path / f"saga-{saga_id}"
        saga_dir.mkdir(parents=True, exist_ok=True)
        file_path = saga_dir / file_name

        # Write to file
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(data)

        # Create reference
        # We use absolute path for the URI
        uri = f"file://{file_path.absolute()}"
        
        return ExternalReference(
            uri=uri,
            size_bytes=len(data),
            content_type="application/octet-stream",
            checksum=hashlib.sha256(data).hexdigest(),
            created_at=datetime.now(),
            ttl_seconds=ttl_seconds,
        )

    async def load(self, uri: str) -> Any:
        if not uri.startswith("file://"):
            msg = f"Invalid URI scheme for FileSystemStorage: {uri}"
            raise ValueError(msg)

        path_str = uri[7:]  # Strip file://
        file_path = Path(path_str)

        if not file_path.exists():
            msg = f"External storage file not found: {path_str}"
            raise FileNotFoundError(msg)

        async with aiofiles.open(file_path, "rb") as f:
            data = await f.read()

        return pickle.loads(data)

    async def delete(self, uri: str) -> None:
        if not uri.startswith("file://"):
            return
            
        path_str = uri[7:]
        file_path = Path(path_str)
        try:
            file_path.unlink()
        except FileNotFoundError:
            pass


class S3ExternalStorage(ExternalStorage):
    """
    S3 implementation for external storage.
    Resulting URI format: s3://bucket/key
    """

    def __init__(
        self,
        bucket: str,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        session_kwargs: dict[str, Any] | None = None,
    ):
        if not HAS_AIOBOTO3:
            msg = "aioboto3 is required for S3ExternalStorage. Install with 'pip install sagaz[aws]'"
            raise ImportError(msg)

        self.bucket = bucket
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.session_kwargs = session_kwargs or {}

    async def store(
        self, saga_id: str, key: str, value: Any, ttl_seconds: int | None = None
    ) -> ExternalReference:
        # Serialize
        data = pickle.dumps(value)
        data_len = len(data)
        
        # Calculate checksum
        checksum = hashlib.sha256(data).hexdigest()

        # Generate unique key
        # Structure: saga_id/key-uuid.bin
        object_key = f"{saga_id}/{key}-{uuid.uuid4()}.bin"
        
        session = aioboto3.Session(**self.session_kwargs)
        async with session.client(
            "s3",
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        ) as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                Metadata={
                    "saga_id": saga_id,
                    "checksum": checksum,
                    "content_type": "application/octet-stream",
                },
            )

        uri = f"s3://{self.bucket}/{object_key}"
        
        return ExternalReference(
            uri=uri,
            size_bytes=data_len,
            content_type="application/octet-stream",
            checksum=checksum,
            created_at=datetime.now(),
            ttl_seconds=ttl_seconds,
        )

    async def load(self, uri: str) -> Any:
        if not uri.startswith("s3://"):
            msg = f"Invalid URI scheme for S3ExternalStorage: {uri}"
            raise ValueError(msg)

        # Parse s3://bucket/key
        parts = uri[5:].split("/", 1)
        if len(parts) != 2:
            msg = f"Invalid S3 URI format: {uri}"
            raise ValueError(msg)
            
        bucket, key = parts
        
        # Security check: ensure bucket matches configured bucket
        if bucket != self.bucket:
             msg = f"URI bucket '{bucket}' does not match configured bucket '{self.bucket}'"
             raise ValueError(msg)

        session = aioboto3.Session(**self.session_kwargs)
        async with session.client(
            "s3",
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        ) as s3:
            try:
                response = await s3.get_object(Bucket=bucket, Key=key)
                async with response["Body"] as stream:
                    data = await stream.read()
            except Exception as e:
                # Map S3 errors to standard exceptions where possible
                err_str = str(e)
                if "NoSuchKey" in err_str or "404" in err_str:
                    msg = f"S3 object not found: {uri}"
                    raise FileNotFoundError(msg) from e
                raise

        return pickle.loads(data)

    async def delete(self, uri: str) -> None:
        if not uri.startswith("s3://"):
            return

        parts = uri[5:].split("/", 1)
        if len(parts) != 2:
            return
            
        bucket, key = parts
        if bucket != self.bucket:
            return

        session = aioboto3.Session(**self.session_kwargs)
        async with session.client(
            "s3",
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        ) as s3:
            await s3.delete_object(Bucket=bucket, Key=key)


@dataclass
class SagaContext:
    """
    Enhanced context passed between saga steps for data sharing.
    
    Supports:
    - Key-value data storage
    - Metadata storage
    - Automatic offloading of large values to external storage
    - Streaming result registration
    """

    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # External references mapping: key -> ExternalReference
    external_refs: dict[str, ExternalReference] = field(default_factory=dict)
    
    # Stream registry: key -> AsyncGenerator
    # Note: Streams are transient and not persisted to DB
    _streams: dict[str, AsyncGenerator] = field(default_factory=dict)
    
    # Configuration for external storage
    _storage_backend: ExternalStorage | None = None
    _saga_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Size tracking limits
    _auto_offload_enabled: bool = False
    _offload_threshold_bytes: int = 1_000_000  # 1MB default

    def configure(
        self, 
        saga_id: str, 
        storage: ExternalStorage | None = None,
        auto_offload: bool = False,
        offload_threshold: int = 1_000_000
    ) -> None:
        """Configure context constraints and backend."""
        self._saga_id = saga_id
        self._storage_backend = storage
        self._auto_offload_enabled = auto_offload
        self._offload_threshold_bytes = offload_threshold

    def set(self, key: str, value: Any) -> None:
        """
        Set a value in the context (Synchronous).
        
        Stores value directly in memory. For large values with auto-offload,
        use `set_async()` instead.
        """
        if isinstance(value, AsyncGenerator):
            self.register_stream(key, value)
            return
            
        self.data[key] = value

    async def set_async(self, key: str, value: Any) -> None:
        """
        Set a value in the context with automatic offloading support.
        """
        # If it's a stream (AsyncGenerator), register it specially
        if isinstance(value, AsyncGenerator):
            self.register_stream(key, value)
            return

        # Check for offloading if valid
        if (
            self._auto_offload_enabled 
            and self._storage_backend 
            and self._should_offload(value)
        ):
            ref = await self.store_external(key, value)
            self.data[key] = {"_external_ref": ref.uri}
        else:
            self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a value from the context (Synchronous).
        
        Returns in-memory data. If data is an external reference,
        returns the reference dict/object, not the loaded content.
        Use `load_external()` or `get_async()` to resolve references.
        """
        # 1. Check if it's a stream
        if key in self._streams:
            return self._streams[key]

        # 2. Standard retrieval
        return self.data.get(key, default)

    async def get_async(self, key: str, default: Any = None) -> Any:
        """
        Get value, automatically resolving external references.
        """
        # 1. Check if it's a stream
        if key in self._streams:
            return self._streams[key]

        # 2. Check if it's explicitly an external ref object (in external_refs)
        if key in self.external_refs:
            return await self.load_external(key)

        # 3. Standard retrieval
        val = self.data.get(key, default)
        
        # 4. Check if it's a dict marked as ref
        if isinstance(val, dict) and "_external_ref" in val and self._storage_backend:
            return await self._storage_backend.load(val["_external_ref"])
            
        return val

    def has(self, key: str) -> bool:
        """Check if a key exists in data, streams, or refs."""
        return (
            key in self.data 
            or key in self._streams 
            or key in self.external_refs
        )

    # --- External Storage Methods ---

    async def store_external(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None
    ) -> ExternalReference:
        """Explicitly store value in external storage."""
        if not self._storage_backend:
            msg = "No external storage backend configured in SagaContext"
            raise RuntimeError(msg)

        ref = await self._storage_backend.store(
            saga_id=self._saga_id,
            key=key,
            value=value,
            ttl_seconds=ttl_seconds
        )
        self.external_refs[key] = ref
        return ref

    async def load_external(self, key: str) -> Any:
        """Explicitly load value from external storage."""
        if not self._storage_backend:
            msg = "No external storage backend configured in SagaContext"
            raise RuntimeError(msg)

        if key not in self.external_refs:
            # Try to see if it is in data as a marker
            val = self.data.get(key)
            if isinstance(val, dict) and "_external_ref" in val:
                return await self._storage_backend.load(val["_external_ref"])
            
            msg = f"No external reference found for key: {key}"
            raise KeyError(msg)
        
        ref = self.external_refs[key]
        return await self._storage_backend.load(ref.uri)

    # --- Streaming Methods ---

    def register_stream(self, key: str, generator: AsyncGenerator) -> None:
        """Register a streaming generator."""
        self._streams[key] = generator

    def stream(self, key: str) -> AsyncGenerator:
        """Get a registered stream for consumption."""
        if key not in self._streams:
            msg = f"No stream registered for key: {key}"
            raise KeyError(msg)
        return self._streams[key]

    # --- Internals ---

    def _should_offload(self, value: Any) -> bool:
        """Determine if value should be offloaded based on estimated size."""
        try:
            size = self._estimate_size(value)
            return size > self._offload_threshold_bytes
        except Exception:
            # If we can't estimate (e.g. unpicklable), don't auto-offload
            return False

    def _estimate_size(self, value: Any) -> int:
        """Estimate size of value in bytes."""
        if isinstance(value, bytes):
            return len(value)
        if isinstance(value, str):
            return len(value.encode("utf-8"))
        
        # Fallback: lightweight pickle check
        return len(pickle.dumps(value))
