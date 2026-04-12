"""External storage for large saga payloads.

Supports storing large or sensitive data outside of saga context with reference-based
access. Includes implementations for filesystem (local) and S3 storage.
"""

import hashlib
import pickle
import uuid
import warnings
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles  # type: ignore[import-untyped]

try:
    import aioboto3

    HAS_AIOBOTO3 = True
except ImportError:
    HAS_AIOBOTO3 = False


class ExternalReference:
    """Reference to externally stored data.

    Dataclass-like object representing a reference to data stored externally.
    Used when saga context stores large payloads outside the main context.
    """

    def __init__(
        self,
        uri: str,
        size_bytes: int,
        content_type: str,
        checksum: str,
        created_at: datetime,
        ttl_seconds: int | None = None,
    ):
        """Initialize external reference.

        Args:
            uri: Storage URI (s3://bucket/key, file:///path/to/file)
            size_bytes: Original data size in bytes
            content_type: MIME type of stored data
            checksum: SHA256 hash of original data
            created_at: Timestamp when data was stored
            ttl_seconds: Auto-cleanup after TTL (optional)
        """
        self.uri = uri
        self.size_bytes = size_bytes
        self.content_type = content_type
        self.checksum = checksum
        self.created_at = created_at
        self.ttl_seconds = ttl_seconds


class ExternalStorage(ABC):
    """Abstract base for external storage backends.

    Defines the interface for storing and retrieving large payloads
    from external storage systems (filesystem, S3, etc).
    """

    @abstractmethod
    async def store(
        self, saga_id: str, key: str, value: Any, ttl_seconds: int | None = None
    ) -> ExternalReference:
        """Store value and return reference.

        Args:
            saga_id: Saga instance identifier
            key: Key for the stored value
            value: Data to store (will be pickled)
            ttl_seconds: Optional time-to-live for auto-cleanup

        Returns:
            ExternalReference with storage URI and metadata
        """
        ...

    @abstractmethod
    async def load(self, uri: str) -> Any:
        """Load value from URI.

        Args:
            uri: ExternalReference URI

        Returns:
            Unpickled original value

        Raises:
            FileNotFoundError: If URI doesn't exist
            ValueError: If URI format is invalid
        """
        ...

    @abstractmethod
    async def delete(self, uri: str) -> None:
        """Delete stored value.

        Args:
            uri: ExternalReference URI
        """
        ...


class FileSystemExternalStorage(ExternalStorage):
    """Local filesystem implementation for external storage.

    Stores payloads as pickle files in the local filesystem.
    Suitable for development and testing.
    """

    def __init__(self, base_path: str):
        """Create (or re-use) the directory at base_path for artifact storage.

        Args:
            base_path: Base directory for storing artifacts
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def store(
        self, saga_id: str, key: str, value: Any, ttl_seconds: int | None = None
    ) -> "ExternalReference":
        """Pickle value and write it to <base_path>/saga-<saga_id>/<key>-<uuid>.bin."""
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
        """Deserialise and return the artifact stored at the file:// uri."""
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
        """Remove the local artifact file at uri; silently ignores missing files."""
        if not uri.startswith("file://"):
            return

        path_str = uri[7:]
        file_path = Path(path_str)
        try:
            file_path.unlink()
        except FileNotFoundError:  # file already absent — nothing to do
            pass


class S3ExternalStorage(ExternalStorage):
    """S3 implementation for external storage.

    Stores payloads in an S3 bucket. Supports AWS S3 and S3-compatible
    services (MinIO, DigitalOcean Spaces, etc).

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
        """Configure the S3 external storage backend.

        Args:
            bucket: Target S3 bucket name
            region_name: AWS region; inferred from environment when None
            endpoint_url: Override endpoint for S3-compatible stores (e.g. MinIO)
            aws_access_key_id: Explicit AWS credentials; uses default chain when None
            aws_secret_access_key: Companion secret for aws_access_key_id
            session_kwargs: Extra kwargs forwarded to aioboto3.Session

        Raises:
            ImportError: If aioboto3 is not installed
        """
        if not HAS_AIOBOTO3:
            msg = (
                "aioboto3 is required for S3ExternalStorage. "
                "Install with 'pip install sagaz[aws]'"
            )
            raise ImportError(msg)

        self.bucket = bucket
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.session_kwargs = session_kwargs or {}

    async def store(
        self, saga_id: str, key: str, value: Any, ttl_seconds: int | None = None
    ) -> "ExternalReference":
        """Pickle value and upload it to S3 under <bucket>/<saga_id>/<key>-<uuid>.bin."""
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
        """Download and deserialise the S3 object at uri (s3://bucket/key)."""
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
        """Delete the S3 object at uri; silently ignores non-matching URIs."""
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
