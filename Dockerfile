# Dockerfile for sagaz Outbox Worker
# Build: docker build -tsagaz-outbox-worker:latest .
# Run: docker run -e DATABASE_URL=... sagaz-outbox-worker:latest

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY sagaz/ ./sage/

# Install the package with postgres and kafka extras
# Use non-editable install for production
RUN pip install --no-cache-dir ".[postgres,kafka,rabbitmq,tracing,prometheus]" && \
    pip install --no-cache-dir asyncpg aiokafka aio-pika prometheus-client && \
    pip list | grep -E "asyncpg|kafka|pika|prometheus"

# Create non-root user
RUN useradd --create-home --shell /bin/bash worker
USER worker

# Environment variables (override in k8s)
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sagaz; print('healthy')" || exit 1

# Default command - run the outbox worker
CMD ["python", "-m", "sage.outbox.worker"]
