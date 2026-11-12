#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_VERSION="${PYTHON_VERSION:-3.14}"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

cd "$ROOT"

for tool in uv docker; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required"
done

docker info >/dev/null 2>&1 ||
    fail "Docker daemon is unavailable. Start Docker Desktop/Engine and retry."

PYTHON_PATH="$(uv python find "$PYTHON_VERSION")" ||
    fail "CPython $PYTHON_VERSION is not installed; install it with 'uv python install $PYTHON_VERSION'."
export UV_PYTHON="$PYTHON_PATH"

printf 'Repository: %s\n' "$ROOT"
printf 'Python: %s\n' "$UV_PYTHON"
printf 'Docker: %s\n' "$(docker info --format '{{.ServerVersion}}')"

uv sync --locked --group dev --extra integration-tests

printf '\n== StateChart and storage unit regressions ==\n'
uv run pytest \
    tests/unit/core/test_state_machine.py \
    tests/unit/core/test_replay.py \
    tests/unit/core/storage \
    -m "not integration" \
    -q --tb=short

printf '\n== PostgreSQL Testcontainers integration suite ==\n'
uv run pytest \
    tests/unit/core/storage/backends/test_storage_postgresql.py \
    -m integration \
    -q --tb=short

printf '\nStateChart Phase 1 hardening checks passed.\n'
