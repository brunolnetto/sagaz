"""
Logging shared by the outbox worker modules.

Every worker helper module logs under the ``sagaz.core.outbox.worker`` logger.
Root logging is configured only when the worker runs as its own process
(:func:`configure_worker_logging`, called by ``worker.main``): importing sagaz
must never change the host application's logging.
"""

import logging
import os

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger("sagaz.core.outbox.worker")


def configure_worker_logging() -> None:
    """Configure root logging from ``LOG_LEVEL``, for the standalone worker process."""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
