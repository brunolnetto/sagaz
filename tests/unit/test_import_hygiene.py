"""``import sagaz`` must stay light and must not touch the host's logging (#532)."""

from __future__ import annotations

import json
import subprocess
import sys

HEAVY = [
    "aioboto3",
    "aiokafka",
    "aio_pika",
    "asyncpg",
    "redis",
    "opentelemetry",
    "rich",
    "click",
    "simple_term_menu",
    "sagaz.cli",
]


def probe(code: str) -> dict:
    """Run ``code`` in a fresh interpreter; it prints a JSON object."""
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=120
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


def test_import_sagaz_leaves_root_logging_alone():
    state = probe(
        "import json, logging; import sagaz; r = logging.getLogger();"
        "print(json.dumps({'handlers': len(r.handlers), 'level': r.level}))"
    )
    assert state == {"handlers": 0, "level": 30}  # Python's defaults: no handler, WARNING


def test_import_sagaz_does_not_load_optional_drivers_or_the_cli():
    loaded = probe(
        "import json, sys; import sagaz;"
        f"print(json.dumps([m for m in {HEAVY!r} if m in sys.modules]))"
    )
    assert loaded == []


def test_lazy_names_still_resolve():
    names = probe(
        "import json, sagaz;"
        "from sagaz.core.storage import PostgreSQLSagaStorage, RedisSagaStorage;"
        "from sagaz.choreography import KafkaEventBus, RabbitMQEventBus, RedisStreamsEventBus;"
        "import sagaz.core.context as c;"
        "print(json.dumps([PostgreSQLSagaStorage.__name__, RedisSagaStorage.__name__,"
        " KafkaEventBus.__name__, RabbitMQEventBus.__name__, RedisStreamsEventBus.__name__,"
        " sagaz.cli_examples.__name__, c.HAS_AIOBOTO3 in (True, False)]))"
    )
    assert names == [
        "PostgreSQLSagaStorage",
        "RedisSagaStorage",
        "KafkaEventBus",
        "RabbitMQEventBus",
        "RedisStreamsEventBus",
        "sagaz.cli.examples",
        True,
    ]


def test_version_is_the_installed_distribution():
    from importlib.metadata import version

    import sagaz

    assert sagaz.__version__ == version("sagaz")


def test_the_worker_process_configures_logging():
    state = probe(
        "import json, logging;"
        "from sagaz.core.outbox._worker_logging import configure_worker_logging;"
        "configure_worker_logging(); r = logging.getLogger();"
        "print(json.dumps({'handlers': len(r.handlers), 'level': r.level}))"
    )
    assert state == {"handlers": 1, "level": 20}
