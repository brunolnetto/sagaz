"""
ServiceManager: reusable context manager for spinning up testcontainer services.

Usage:
    with ServiceManager(postgres=True, redis=True) as svc:
        await run_demo(
            pg_url=svc.postgres_url,
            redis_url=svc.redis_url,
        )
    # containers are stopped automatically on context exit
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("sagaz.demonstrations.utils.service_manager")


@dataclass
class ServiceURLs:
    """Connection URLs for provisioned services."""

    postgres_url: str | None = None
    redis_url: str | None = None


@contextmanager
def ServiceManager(*, postgres: bool = False, redis: bool = False):
    """
    Context manager that provisions testcontainer services on enter and tears
    them down on exit (including on exceptions).

    Args:
        postgres: Start a PostgreSQL container.
        redis: Start a Redis container.

    Yields:
        ServiceURLs with connection URLs for each requested service.

    Example:
        with ServiceManager(postgres=True, redis=True) as svc:
            await run(svc.postgres_url, svc.redis_url)
    """
    containers: list[Any] = []
    urls = ServiceURLs()

    try:
        if postgres:
            from testcontainers.postgres import PostgresContainer

            pg = PostgresContainer("postgres:16-alpine")
            pg.start()
            containers.append(pg)
            urls.postgres_url = pg.get_connection_url().replace(
                "postgresql+psycopg2://", "postgresql://"
            )
            logger.info("PostgreSQL container started: %s", urls.postgres_url)

        if redis:
            from testcontainers.redis import RedisContainer

            r = RedisContainer("redis:7-alpine")
            r.start()
            containers.append(r)
            host = r.get_container_host_ip()
            port = r.get_exposed_port(6379)
            urls.redis_url = f"redis://{host}:{port}/0"
            logger.info("Redis container started: %s", urls.redis_url)

        yield urls

    finally:
        for container in reversed(containers):
            try:
                container.stop()
                logger.info("Container stopped: %s", type(container).__name__)
            except Exception:
                logger.exception(
                    "Error stopping container %s", type(container).__name__
                )
