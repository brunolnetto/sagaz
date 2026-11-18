"""Runtime validation of a saga context against its version's schema (ADR-018).

A :class:`SagaVersion` schema is either

* a mapping of context field names to type descriptors — ``"str"``, ``"int"``,
  ``"float"`` (ints accepted), ``"bool"``, ``"dict"``, ``"list"`` or ``"any"``;
  a trailing ``"?"`` makes the field optional (``"str?"``), or
* a Pydantic model class (anything with ``model_validate``), so Pydantic stays
  an optional dependency.

Fields not mentioned in the schema are allowed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sagaz.versioning.exceptions import SagaVersionSchemaError
from sagaz.versioning.saga_version import SagaVersion

_TYPES: dict[str, tuple[type, ...]] = {
    "str": (str,),
    "int": (int,),
    "float": (int, float),
    "bool": (bool,),
    "dict": (dict,),
    "list": (list,),
}


def _type_violation(field: str, descriptor: str, value: Any) -> str | None:
    if descriptor == "any":
        return None
    expected = _TYPES.get(descriptor)
    if expected is None:
        return f"'{field}': unknown type descriptor '{descriptor}'"
    # bool is a subclass of int; it only satisfies the "bool" descriptor.
    if isinstance(value, bool) and descriptor != "bool":
        return f"'{field}': expected {descriptor}, got bool"
    if not isinstance(value, expected):
        return f"'{field}': expected {descriptor}, got {type(value).__name__}"
    return None


def _model_violations(validator: Any, context: Mapping[str, Any]) -> list[str]:
    try:
        validator(dict(context))
    except Exception as exc:  # pydantic.ValidationError, without importing pydantic
        errors = getattr(exc, "errors", None)
        if not callable(errors):
            return [str(exc)]
        return [
            f"'{'.'.join(str(p) for p in err.get('loc', ()))}': {err.get('msg', '')}"
            for err in errors()
        ]
    return []


def _field_violation(field: str, raw: Any, context: Mapping[str, Any]) -> str | None:
    descriptor = str(raw).strip()
    optional = descriptor.endswith("?")
    descriptor = descriptor.rstrip("?")
    if context.get(field) is None:
        return None if optional else f"'{field}': required field is missing"
    return _type_violation(field, descriptor, context[field])


def schema_violations(schema: Any, context: Mapping[str, Any]) -> list[str]:
    """Return human-readable violations of ``schema`` by ``context`` (empty if valid)."""
    validator = getattr(schema, "model_validate", None)
    if callable(validator):
        return _model_violations(validator, context)
    found = (_field_violation(field, raw, context) for field, raw in (schema or {}).items())
    return [problem for problem in found if problem]


def validate_context(saga_version: SagaVersion, context: Mapping[str, Any]) -> None:
    """Raise :class:`SagaVersionSchemaError` if ``context`` violates the version's schema."""
    violations = schema_violations(saga_version.schema, context)
    if violations:
        raise SagaVersionSchemaError(saga_version.saga_name, str(saga_version.version), violations)
