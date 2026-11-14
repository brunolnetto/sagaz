"""A minimal in-process stand-in for ``redis.asyncio.Redis``.

Implements only the commands ``RedisOutboxStorage`` uses (hashes, sets, scan,
streams with consumer groups, pipelines and WATCH), returning ``bytes`` like a
client created without ``decode_responses``. It lets the outbox contract tests
run against the Redis backend without a container.
"""

from __future__ import annotations

import fnmatch
import time
from typing import Any


def _b(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode()


class _Group:
    def __init__(self, start: int) -> None:
        self.next_index = start
        self.pending: dict[bytes, tuple[bytes, float]] = {}


class _Stream:
    def __init__(self) -> None:
        self.entries: list[tuple[bytes, dict[bytes, bytes]]] = []
        self.groups: dict[str, _Group] = {}
        self.seq = 0


class FakeRedis:
    """Async fake of the subset of redis-py used by the outbox backend."""

    def __init__(self) -> None:
        self.hashes: dict[bytes, dict[bytes, bytes]] = {}
        self.sets: dict[bytes, set[bytes]] = {}
        self.streams: dict[bytes, _Stream] = {}

    # ── generic ──

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    def _keys(self) -> list[bytes]:
        return [*self.hashes, *self.sets, *self.streams]

    async def exists(self, *keys: Any) -> int:
        return sum(1 for key in keys if _b(key) in self._keys())

    async def delete(self, *keys: Any) -> int:
        removed = 0
        for key in map(_b, keys):
            for store in (self.hashes, self.sets, self.streams):
                if store.pop(key, None) is not None:
                    removed += 1
        return removed

    async def expire(self, key: Any, seconds: int) -> bool:
        return _b(key) in self._keys()

    async def scan(self, cursor: int, match: str = "*", count: int = 10):
        keys = [key for key in self._keys() if fnmatch.fnmatchcase(key.decode(), match)]
        return 0, keys

    # ── hashes ──

    async def hset(self, key: Any, field: Any = None, value: Any = None, mapping=None) -> int:
        target = self.hashes.setdefault(_b(key), {})
        items = dict(mapping or {})
        if field is not None:
            items[field] = value
        for k, v in items.items():
            target[_b(k)] = _b(v)
        return len(items)

    async def hgetall(self, key: Any) -> dict[bytes, bytes]:
        return dict(self.hashes.get(_b(key), {}))

    async def hdel(self, key: Any, *fields: Any) -> int:
        target = self.hashes.get(_b(key), {})
        return sum(1 for field in fields if target.pop(_b(field), None) is not None)

    # ── sets ──

    async def sadd(self, key: Any, *members: Any) -> int:
        target = self.sets.setdefault(_b(key), set())
        before = len(target)
        target.update(map(_b, members))
        return len(target) - before

    async def smembers(self, key: Any) -> set[bytes]:
        return set(self.sets.get(_b(key), set()))

    # ── streams ──

    def _stream(self, key: Any) -> _Stream:
        return self.streams.setdefault(_b(key), _Stream())

    async def xadd(self, key: Any, fields: dict, maxlen: int | None = None) -> bytes:
        stream = self._stream(key)
        stream.seq += 1
        message_id = f"{int(time.time() * 1000)}-{stream.seq}".encode()
        stream.entries.append((message_id, {_b(k): _b(v) for k, v in fields.items()}))
        return message_id

    async def xlen(self, key: Any) -> int:
        stream = self.streams.get(_b(key))
        return len(stream.entries) if stream else 0

    async def xgroup_create(self, key: Any, group: str, id: str = "$", mkstream=False) -> bool:
        from redis.exceptions import ResponseError

        if _b(key) not in self.streams and not mkstream:
            msg = "ERR no such key"
            raise ResponseError(msg)
        stream = self._stream(key)
        if group in stream.groups:
            msg = "BUSYGROUP Consumer Group name already exists"
            raise ResponseError(msg)
        stream.groups[group] = _Group(0 if id == "0" else len(stream.entries))
        return True

    async def xreadgroup(self, groupname, consumername, streams, count=None, block=None):
        from redis.exceptions import ResponseError

        response = []
        for key in streams:
            stream = self.streams.get(_b(key))
            if stream is None or groupname not in stream.groups:
                msg = "NOGROUP No such key or consumer group"
                raise ResponseError(msg)
            group = stream.groups[groupname]
            batch = stream.entries[group.next_index : group.next_index + (count or 10**9)]
            group.next_index += len(batch)
            for message_id, _ in batch:
                group.pending[message_id] = (_b(consumername), time.time())
            if batch:
                response.append([_b(key), batch])
        return response

    async def xack(self, key: Any, group: str, *ids: Any) -> int:
        stream = self.streams.get(_b(key))
        if stream is None or group not in stream.groups:
            return 0
        pending = stream.groups[group].pending
        return sum(1 for i in ids if pending.pop(_b(i), None) is not None)

    async def xpending_range(self, key, groupname, min="-", max="+", count=100):
        stream = self.streams.get(_b(key))
        if stream is None or groupname not in stream.groups:
            return []
        now = time.time()
        return [
            {
                "message_id": message_id,
                "consumer": consumer,
                "time_since_delivered": int((now - since) * 1000),
                "times_delivered": 1,
            }
            for message_id, (consumer, since) in list(stream.groups[groupname].pending.items())
        ][:count]

    async def xclaim(self, key, groupname, consumername, min_idle_time, message_ids):
        pending = self.streams[_b(key)].groups[groupname].pending
        for message_id in map(_b, message_ids):
            if message_id in pending:
                pending[message_id] = (_b(consumername), time.time())
        return message_ids

    # ── pipelines ──

    def pipeline(self, transaction: bool = True) -> _Pipeline:
        return _Pipeline(self)


class _Pipeline:
    """Queues commands; ``watch``/``hgetall`` before ``multi()`` run immediately."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._queue: list[tuple[str, tuple, dict]] = []
        self._immediate = False

    async def __aenter__(self) -> _Pipeline:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._queue.clear()

    async def watch(self, *keys: Any) -> None:
        self._immediate = True

    async def unwatch(self) -> None:
        self._immediate = False

    def multi(self) -> None:
        self._immediate = False

    def __getattr__(self, name: str):
        command = getattr(self._redis, name)

        def queue(*args, **kwargs):
            if self._immediate:
                return command(*args, **kwargs)
            self._queue.append((name, args, kwargs))
            return self

        return queue

    async def execute(self) -> list:
        results = [
            await getattr(self._redis, name)(*args, **kwargs) for name, args, kwargs in self._queue
        ]
        self._queue.clear()
        return results


async def fake_redis_outbox(prefix: str = "test:outbox"):
    """A ``RedisOutboxStorage`` wired to a fresh :class:`FakeRedis`."""
    from sagaz.core.storage.backends.redis import RedisOutboxStorage

    storage = RedisOutboxStorage(redis_url="redis://fake", prefix=prefix, consumer_group="g")
    storage._redis = FakeRedis()
    await storage._ensure_group(storage._stream_key)
    storage._initialized = True
    return storage
