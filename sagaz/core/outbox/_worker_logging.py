"""
Logging setup shared by the outbox worker modules.

Configures root logging from ``LOG_LEVEL`` (the worker runs as a standalone
process) and exposes the worker logger. Every worker helper module imports
this first, so logging is configured before anything is logged, and all of
them log under the ``sagaz.core.outbox.worker`` logger name.
"""

import logging
import os

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("sagaz.core.outbox.worker")
