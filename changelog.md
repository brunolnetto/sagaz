# Changelog

All notable changes to the Sagaz Saga Pattern library will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.0] - 2026-04-23

### Added

#### Core Storage Refactor
- **NEW:** Moved `SagaStorageMigrator` and `transfer_data` to `sagaz.core.storage` namespace.
- **NEW:** Modularized storage transfer logic to support future multi-cloud backends.
- **NEW:** Introduced compatibility facades in `sagaz.storage.migration` for backward compatibility.

#### Quality & CLI Improvements
- **NEW:** Comprehensive unit test suite for `sagaz migrate` and `sagaz visualize` commands.
- **NEW:** Resolved `PytestUnhandledThreadExceptionWarning` by improving `AsyncMock` cleanup in storage tests.
- **NEW:** Integrated Husky hooks for commit message and branch naming validation.

## [1.5.0] - 2026-04-15

### Added

#### Architectural Evolution
- **Core Reorganization**: Massive refactoring of the internal structure into dedicated `core` modules (exceptions, types, hooks, observers).
- **Lifecycle Hooks**: Added `on_step_exit` and global saga-level event dispatching for better observability.
- **Alerting Integration**: Introduced AlertManager rules templates and a comprehensive alerting guide.

#### Reliability & Compatibility
- **Backward Compatibility**: Restored inheritance and added shims for execution engine methods to ensure zero-breakage during the `core` migration.
- **Thread Safety**: Fixed race conditions in `aiosqlite` and increased Testcontainers timeouts for more resilient CI runs.
- **Type Safety**: Achieved 100% mypy compliance across the entire `sagaz/` package.

## [1.4.0] - 2026-01-12

### Added
- **Context Streaming**: Implemented lightweight context streaming (ADR-021) to optimize memory usage in long-running sagas.
- **Industry Vertical Expansion**: Added 24 production-grade examples covering 12 industry sectors (FinTech, HealthTech, E-commerce, etc.).

## [1.3.0] - 2026-01-11

### Added

#### Developer Experience
- **Simplified Dry-Run**: Replaced complex dry-run logic with straightforward `validate` and `simulate` commands.
- **Interactive CLI**: Enhanced the `sagaz init` command to be fully interactive, including template and domain-based example selection.

#### Security & Integrations
- **Webhook Idempotency**: Added native support for HTTP-level idempotency key validation in webhooks.
- **Framework Adapters**: Improved status tracking for FastAPI, Django, and Flask integrations.

## [1.0.0 - 1.2.0] - 2025-12-26

### Added
- **Initial Release**: Core Saga Pattern, Transactional Outbox, and PostgreSQL/Redis storage backends.
- **Observability**: Prometheus metrics and basic Mermaid diagram generation for saga visualization.
- **Cloud Native**: Initial Kubernetes manifests and Helm chart support.

---
*For a detailed list of every commit, please refer to the Git history.*
