"""
JSON serialization utilities for storage backends.

Provides consistent serialization/deserialization across all backends
with support for datetime, UUID, Enum, and custom types.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from .errors import SerializationError


class StorageEncoder(json.JSONEncoder):
    """
    JSON encoder for storage data.
    
    Handles:
    - datetime -> ISO format string
    - UUID -> string
    - Enum -> value
    - Decimal -> string (preserves precision)
    - bytes -> base64 string
    - set -> list
    """

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return {"__type__": "datetime", "value": obj.isoformat()}
        if isinstance(obj, UUID):
            return {"__type__": "uuid", "value": str(obj)}
        if isinstance(obj, Enum):
            return {"__type__": "enum", "class": f"{obj.__class__.__module__}.{obj.__class__.__name__}", "value": obj.value}
        if isinstance(obj, Decimal):
            return {"__type__": "decimal", "value": str(obj)}
        if isinstance(obj, bytes):
            import base64
            return {"__type__": "bytes", "value": base64.b64encode(obj).decode("ascii")}
        if isinstance(obj, set):
            return {"__type__": "set", "value": list(obj)}
        if isinstance(obj, frozenset):
            return {"__type__": "frozenset", "value": list(obj)}
        
        # Try to serialize as dict
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        
        return super().default(obj)  # pragma: no cover


def storage_decoder(obj: dict[str, Any]) -> Any:
    """
    JSON decoder hook for storage data.
    
    Reverses StorageEncoder transformations.
    """
    if "__type__" not in obj:
        return obj
    
    type_name = obj["__type__"]
    value = obj.get("value")
    
    if type_name == "datetime":
        return datetime.fromisoformat(value)
    if type_name == "uuid":
        return UUID(value)
    if type_name == "decimal":
        return Decimal(value)
    if type_name == "bytes":
        import base64
        return base64.b64decode(value)
    if type_name == "set":
        return set(value)
    if type_name == "frozenset":
        return frozenset(value)
    if type_name == "enum":
        # We can't restore the exact enum without the class
        # Return the value for compatibility
        return value
    
    return obj


def serialize(data: Any) -> str:
    """
    Serialize data to JSON string.
    
    Args:
        data: Any JSON-serializable data
        
    Returns:
        JSON string
        
    Raises:
        SerializationError: If serialization fails
    """
    try:
        return json.dumps(data, cls=StorageEncoder, ensure_ascii=False)
    except (TypeError, ValueError) as e:  # pragma: no cover
        raise SerializationError(
            message=f"Failed to serialize data: {e}",
            operation="serialize",
            data_type=type(data).__name__,
        ) from e


def deserialize(data: str | bytes) -> Any:
    """
    Deserialize JSON string to Python object.
    
    Args:
        data: JSON string or bytes
        
    Returns:
        Deserialized Python object
        
    Raises:
        SerializationError: If deserialization fails
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    
    try:
        return json.loads(data, object_hook=storage_decoder)
    except (json.JSONDecodeError, ValueError) as e:
        raise SerializationError(
            message=f"Failed to deserialize data: {e}",
            operation="deserialize",
        ) from e


def serialize_for_redis(data: dict[str, Any]) -> dict[str, str]:
    """
    Serialize dict values for Redis HSET (all values must be strings).
    
    Args:
        data: Dictionary with any values
        
    Returns:
        Dictionary with all string values
    """
    result = {}
    for key, value in data.items():
        if value is None:
            result[key] = ""
        elif isinstance(value, bool):  # Check bool BEFORE int (bool is subclass of int)
            result[key] = "true" if value else "false"
        elif isinstance(value, str):
            result[key] = value
        elif isinstance(value, (int, float)):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, UUID):
            result[key] = str(value)
        else:
            # Complex types get JSON encoded
            result[key] = serialize(value)
    return result


def deserialize_from_redis(
    data: dict[bytes | str, bytes | str],
    schema: dict[str, type] | None = None,
) -> dict[str, Any]:
    """
    Deserialize Redis HGETALL result.
    
    Args:
        data: Redis hash data (may have bytes keys/values)
        schema: Optional type hints for conversion
        
    Returns:
        Dictionary with typed values
    """
    result = {}
    schema = schema or {}
    
    for key, value in data.items():
        # Decode bytes to string
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        
        # Empty string -> None
        if value == "":
            result[key] = None
            continue
        
        # Use schema hint if available
        expected_type = schema.get(key)
        
        if expected_type == int:
            result[key] = int(value)
        elif expected_type == float:
            result[key] = float(value)
        elif expected_type == bool:
            result[key] = value.lower() in ("true", "1", "yes")
        elif expected_type == datetime:
            result[key] = datetime.fromisoformat(value)
        elif expected_type == UUID:
            result[key] = UUID(value)
        elif value.startswith(("{", "[")):
            # Looks like JSON
            try:
                result[key] = deserialize(value)
            except SerializationError:
                result[key] = value
        else:
            result[key] = value
    
    return result
