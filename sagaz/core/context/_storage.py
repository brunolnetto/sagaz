"""External storage for large saga payloads.

Supports storing large or sensitive data outside of saga context with reference-based
access. Includes implementations for filesystem (local) and S3 storage.
"""

import hashlib
import importlib.util
import pickle
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles  # type: ignore[import-untyped]

from sagaz.core.context._signing import resolve_key, seal, unseal

# aioboto3 takes about a second to import: check it is installed, import it on use.
try:
    HAS_AIOBOTO3 = importlib.util.find_spec("aioboto3") is not None
except (ImportError, ValueError):
    HAS_AIOBOTO3 = False


def _aioboto3() -> Any:
    """The aioboto3 module, or None when it is not installed."""
    try:
        import aioboto3
    except ImportError:
        return None
    return aioboto3


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

    Stores payloads as signed pickle files in the local filesystem, and only reads
    and deletes files under ``base_path``. Suitable for development and testing.
    """

    def __init__(
        self,
        base_path: str,
        *,
        signing_key: bytes | str | None = None,
        allow_unsigned: bool = False,
    ):
        """Create (or re-use) the directory at base_path for artifact storage.

        Args:
            base_path: Base directory for storing artifacts
            signing_key: HMAC key that signs each payload (at least 16 bytes); defaults
                to ``$SAGAZ_EXTERNAL_STORAGE_KEY``. Every process that loads the payloads
                needs the same key.
            allow_unsigned: Also load unsigned payloads, written before signing existed.
                Unsafe when others can write to ``base_path``: use it only to migrate.

        Raises:
            ValueError: If there is no signing key, or it is shorter than 16 bytes
        """
        self._key = resolve_key(signing_key)
        self.allow_unsigned = allow_unsigned
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _inside(self, path: Path) -> Path | None:
        """``path`` resolved, if it lies under ``base_path``; else None."""
        resolved = path.resolve()
        return resolved if resolved.is_relative_to(self.base_path.resolve()) else None

    def _name(self, path: Path) -> str:
        return path.relative_to(self.base_path.resolve()).as_posix()

    async def store(
        self, saga_id: str, key: str, value: Any, ttl_seconds: int | None = None
    ) -> "ExternalReference":
        """Pickle value and write it, signed, to <base_path>/saga-<saga_id>/<key>-<uuid>.bin."""
        # Serialize
        data = pickle.dumps(value)

        # Create file path
        # Use a random UUID to avoid collisions for same key in same saga (e.g. loops)
        file_name = f"{key}-{uuid.uuid4()}.bin"
        saga_dir = self.base_path / f"saga-{saga_id}"
        saga_dir.mkdir(parents=True, exist_ok=True)
        file_path = self._inside(saga_dir / file_name)
        if file_path is None:
            msg = f"Key {key!r} of saga {saga_id!r} would be stored outside {self.base_path}"
            raise ValueError(msg)

        # Write to file
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(seal(self._key, self._name(file_path), data))

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
        file_path = self._inside(Path(path_str))
        if file_path is None:
            msg = f"URI {uri} is outside the storage directory {self.base_path}"
            raise ValueError(msg)

        if not file_path.exists():
            msg = f"External storage file not found: {path_str}"
            raise FileNotFoundError(msg)

        async with aiofiles.open(file_path, "rb") as f:
            blob = await f.read()

        data = unseal(self._key, self._name(file_path), blob, allow_unsigned=self.allow_unsigned)
        return pickle.loads(data)  # nosec B301 - signature verified by unseal

    async def delete(self, uri: str) -> None:
        """Remove the local artifact file at uri; silently ignores missing files."""
        if not uri.startswith("file://"):
            return

        file_path = self._inside(Path(uri[7:]))
        if file_path is None:  # not ours: never delete outside base_path
            return
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
        *,
        signing_key: bytes | str | None = None,
        allow_unsigned: bool = False,
    ):
        """Configure the S3 external storage backend.

        Args:
            bucket: Target S3 bucket name
            region_name: AWS region; inferred from environment when None
            endpoint_url: Override endpoint for S3-compatible stores (e.g. MinIO)
            aws_access_key_id: Explicit AWS credentials; uses default chain when None
            aws_secret_access_key: Companion secret for aws_access_key_id
            session_kwargs: Extra kwargs forwarded to aioboto3.Session
            signing_key: HMAC key that signs each payload (at least 16 bytes); defaults
                to ``$SAGAZ_EXTERNAL_STORAGE_KEY``. Every process that loads the payloads
                needs the same key.
            allow_unsigned: Also load unsigned payloads, written before signing existed.
                Unsafe when others can write to the bucket: use it only to migrate.

        Raises:
            ImportError: If aioboto3 is not installed
            ValueError: If there is no signing key, or it is shorter than 16 bytes
        """
        if not HAS_AIOBOTO3:
            msg = (
                "aioboto3 is required for S3ExternalStorage. Install with 'pip install sagaz[aws]'"
            )
            raise ImportError(msg)

        self._key = resolve_key(signing_key)
        self.allow_unsigned = allow_unsigned
        self.bucket = bucket
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.session_kwargs = session_kwargs or {}

    async def store(
        self, saga_id: str, key: str, value: Any, ttl_seconds: int | None = None
    ) -> "ExternalReference":
        """Pickle value and upload it, signed, to S3 under <bucket>/<saga_id>/<key>-<uuid>.bin."""
        # Serialize
        data = pickle.dumps(value)
        data_len = len(data)

        # Calculate checksum
        checksum = hashlib.sha256(data).hexdigest()

        # Generate unique key
        # Structure: saga_id/key-uuid.bin
        object_key = f"{saga_id}/{key}-{uuid.uuid4()}.bin"

        session = _aioboto3().Session(**self.session_kwargs)
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
                Body=seal(self._key, object_key, data),
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

        session = _aioboto3().Session(**self.session_kwargs)
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
                    blob = await stream.read()
            except Exception as e:
                # Map S3 errors to standard exceptions where possible
                err_str = str(e)
                if "NoSuchKey" in err_str or "404" in err_str:
                    msg = f"S3 object not found: {uri}"
                    raise FileNotFoundError(msg) from e
                raise

        data = unseal(self._key, key, blob, allow_unsigned=self.allow_unsigned)
        return pickle.loads(data)  # nosec B301 - signature verified by unseal

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

        session = _aioboto3().Session(**self.session_kwargs)
        async with session.client(
            "s3",
            region_name=self.region_name,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        ) as s3:
            await s3.delete_object(Bucket=bucket, Key=key)
