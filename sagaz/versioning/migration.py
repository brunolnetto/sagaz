"""MigrationEngine — context schema migration between saga versions (ADR-018)."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable

from sagaz.versioning.exceptions import MigrationPathNotFoundError


class MigrationEngine:
    """
    Manage and apply context-schema migration functions between saga versions.

    Migration functions are registered as directed edges in a graph
    ``from_version -> to_version``.  Multi-hop paths are resolved via BFS.

    Usage::

        engine = MigrationEngine()
        engine.register("order-processing", "1.0.0", "2.0.0", lambda ctx: {**ctx, "tier": "standard"})
        migrated = engine.migrate("order-processing", "1.0.0", "2.0.0", context)
    """

    def __init__(self) -> None:
        # { saga_name: { from_ver: { to_ver: migrate_fn } } }
        self._migrations: dict[str, dict[str, dict[str, Callable[[dict], dict]]]] = defaultdict(
            lambda: defaultdict(dict)
        )

    # ── write ──

    def register(
        self,
        saga_name: str,
        from_version: str,
        to_version: str,
        migrate_fn: Callable[[dict], dict],
    ) -> None:
        """Register a single-hop migration function."""
        from sagaz.versioning.version import Version

        nfrom = str(Version.parse(from_version))
        nto = str(Version.parse(to_version))
        self._migrations[saga_name][nfrom][nto] = migrate_fn

    # ── read ──

    def list_migrations(self, saga_name: str) -> list[tuple[str, str]]:
        """Return all registered ``(from_version, to_version)`` pairs."""
        return [
            (from_ver, to_ver)
            for from_ver, targets in self._migrations.get(saga_name, {}).items()
            for to_ver in targets
        ]

    # ── apply ──

    def migrate(
        self,
        saga_name: str,
        from_version: str,
        to_version: str,
        context: dict,
    ) -> dict:
        """
        Migrate *context* from *from_version* to *to_version*.

        Same-version calls return the context unchanged (no copy).
        Multi-hop paths are resolved automatically.

        Raises :class:`MigrationPathNotFoundError` when no path exists.
        """
        from sagaz.versioning.version import Version

        from_version = str(Version.parse(from_version))
        to_version = str(Version.parse(to_version))
        if from_version == to_version:
            return context

        path = self._find_path(saga_name, from_version, to_version)
        result = dict(context)
        for step_from, step_to in path:
            fn = self._migrations[saga_name][step_from][step_to]
            result = fn(result)
        return result

    # ── internal ──

    def _find_path(
        self,
        saga_name: str,
        from_version: str,
        to_version: str,
    ) -> list[tuple[str, str]]:
        """
        BFS over the migration graph to find the shortest hop path.

        Returns a list of ``(from_ver, to_ver)`` tuples to apply in order.
        """
        graph = self._migrations.get(saga_name, {})
        # BFS
        queue: deque[tuple[str, list[tuple[str, str]]]] = deque()
        queue.append((from_version, []))
        visited: set[str] = {from_version}

        while queue:
            current, path = queue.popleft()
            for neighbour in graph.get(current, {}):
                new_path = [*path, (current, neighbour)]
                if neighbour == to_version:
                    return new_path
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append((neighbour, new_path))

        raise MigrationPathNotFoundError(saga_name, from_version, to_version)
