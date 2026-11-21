"""HMAC signing of external storage payloads.

External storage pickles values, and unpickling runs code: whoever can write to the
directory or bucket could otherwise run code in every worker that loads a payload.
Each payload is therefore stored as ``MAGIC + HMAC-SHA256(key, name + data) + data`` and
its tag is checked before anything is unpickled. ``name`` is the payload's path inside
the storage, so a valid payload cannot be passed off under another name either.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

logger = logging.getLogger(__name__)

#: Environment variable read when no ``signing_key`` is passed.
KEY_ENV = "SAGAZ_EXTERNAL_STORAGE_KEY"

_MAGIC = b"SGZ1"
_TAG_SIZE = hashlib.sha256().digest_size
_MIN_KEY_BYTES = 16


class ExternalStorageIntegrityError(ValueError):
    """A stored payload is unsigned, or its signature does not match: it was not loaded."""


def resolve_key(signing_key: bytes | str | None) -> bytes:
    """The signing key: ``signing_key``, else ``$SAGAZ_EXTERNAL_STORAGE_KEY``."""
    key = signing_key if signing_key is not None else os.environ.get(KEY_ENV)
    if not key:
        msg = (
            "External storage needs a signing key: payloads are pickled, and the key "
            "stops a tampered payload from running code when it is loaded. Pass "
            f"signing_key=... or set {KEY_ENV}, e.g. to the output of "
            "`python -c 'import secrets; print(secrets.token_hex(32))'`. "
            "Every process that loads the payloads needs the same key."
        )
        raise ValueError(msg)
    raw = key.encode() if isinstance(key, str) else bytes(key)
    if len(raw) < _MIN_KEY_BYTES:
        msg = f"The external storage signing key must be at least {_MIN_KEY_BYTES} bytes"
        raise ValueError(msg)
    return raw


def _tag(key: bytes, name: str, data: bytes) -> bytes:
    return hmac.new(key, name.encode() + b"\0" + data, hashlib.sha256).digest()


def seal(key: bytes, name: str, data: bytes) -> bytes:
    """``data`` prefixed with its signature, as stored."""
    return _MAGIC + _tag(key, name, data) + data


def unseal(key: bytes, name: str, blob: bytes, *, allow_unsigned: bool = False) -> bytes:
    """The data of a stored ``blob``, once its signature is verified.

    Raises:
        ExternalStorageIntegrityError: the blob is unsigned (unless ``allow_unsigned``)
            or its signature does not match ``key`` and ``name``.
    """
    if not blob.startswith(_MAGIC):
        if not allow_unsigned:
            msg = (
                f"External payload {name!r} is not signed: refusing to unpickle it. "
                "Payloads stored before signing was introduced can be read once with "
                "allow_unsigned=True, which is unsafe if others can write to the storage."
            )
            raise ExternalStorageIntegrityError(msg)
        logger.warning("Loading unsigned external payload %r (allow_unsigned=True)", name)
        return blob
    tag, data = blob[len(_MAGIC) : len(_MAGIC) + _TAG_SIZE], blob[len(_MAGIC) + _TAG_SIZE :]
    if not hmac.compare_digest(tag, _tag(key, name, data)):
        msg = (
            f"External payload {name!r} failed signature verification: it was modified, "
            "written under another name, or signed with another key. It was not loaded."
        )
        raise ExternalStorageIntegrityError(msg)
    return data
