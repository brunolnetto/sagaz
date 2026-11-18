# sagaz outbox worker image
#
# Build:  docker build -t sagaz-outbox-worker:latest .
# Run:    docker run -e DATABASE_URL=postgresql://... -e BROKER_TYPE=redis \
#                    -e REDIS_URL=redis://... sagaz-outbox-worker:latest
#
# The worker reads its configuration from the environment
# (sagaz/core/outbox/_worker_bootstrap.py): DATABASE_URL, BROKER_TYPE
# (kafka | rabbitmq | redis) with KAFKA_BOOTSTRAP_SERVERS / RABBITMQ_URL /
# REDIS_URL, and SAGAZ_OUTBOX_MODE=cdc for change data capture.

FROM python:3.15-slim

WORKDIR /app

# Build tools for dependencies without wheels for this Python version.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# pyproject.toml declares README.md as the package readme, so the build needs it.
COPY pyproject.toml README.md ./
COPY sagaz/ ./sagaz/

# Storage, every supported broker, CDC sources and Prometheus metrics.
RUN pip install --no-cache-dir ".[postgres,redis,kafka,rabbitmq,cdc,prometheus]"

# Run as an unprivileged user.
RUN useradd --create-home --shell /bin/bash --uid 1000 worker
USER worker

ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sagaz.core.outbox.worker" || exit 1

CMD ["python", "-m", "sagaz.core.outbox.worker"]
