from .snapshot import S3SnapshotStorage

try:
    import aioboto3

    AIOBOTO3_AVAILABLE = True
except ImportError:
    AIOBOTO3_AVAILABLE = False
    aioboto3 = None

__all__ = ["AIOBOTO3_AVAILABLE", "S3SnapshotStorage", "aioboto3"]
