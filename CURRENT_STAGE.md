# CURRENT STAGE

- **Current Version:** V0
- **Status:** IN PROGRESS — V0-T1 skeleton prepared; implementation not started
- **Verified On:** 2026-08-30

## Entry Check

- `plans/V0.md` declares no previous-version dependency.
- The working directory contains project documents only; no Python application code,
  test suite, or `pyproject.toml` existed when V0 started.
- The working directory has no `.git` metadata, so Git status, commit history, and
  version tags are currently unavailable.
- Local WSL reports Python 3.12.3 and a `pytest` executable. Ruff, mypy, and pyright
  were not found on `PATH` during the check.

## Stage Goal

Establish a runnable, migratable, and testable Python backend baseline for the
modular monolith described in `plans/V0.md`.

## Scope

- Python 3.12 project metadata and development tooling.
- Typed configuration for development and test environments, with secrets supplied
  through environment variables.
- FastAPI application entry point, `/health`, and versioned `/api/v1/ping` routing.
- PostgreSQL connectivity, SQLAlchemy 2.x sessions, and Alembic migrations.
- Consistent API errors, request IDs, and basic structured logging.
- Focused automated tests and setup/operation documentation.

## Task Breakdown

- [ ] **V0-T1:** Create the Python tooling and typed configuration baseline.
- [ ] **V0-T2:** Add the FastAPI application factory and versioned ping route.
- [ ] **V0-T3:** Add the SQLAlchemy session boundary and Alembic baseline.
- [ ] **V0-T4:** Add database-aware health/readiness behavior.
- [ ] **V0-T5:** Add request IDs, structured logging, and unified API errors.
- [ ] **V0-T6:** Complete V0 verification tests and the fresh-machine README workflow.

Each task remains incomplete until its implementation is reviewed and receives
`PASS`.

## Current Task

**V0-T1 — Python tooling and typed configuration baseline**

Only its skeleton exists. Core implementation and tests are intentionally left for
the user.

## Definition of Done

- A new machine can follow the README and start the service within 15 minutes.
- An empty PostgreSQL database can upgrade to the latest migration and downgrade
  the most recent migration.
- `/health`, `/docs`, pytest, and lint all work.
- Request logs include a request ID.

## Out of Scope

- Redis, Celery, MQTT, JWT, and WebSocket.
- Frontend work, microservices, Kubernetes, Kafka, complex DDD, and general-purpose
  framework abstractions.
- Any V1-V6 domain modules or placeholder architecture.

## Progress Notes

- V0 entry facts were checked against the local directory and `plans/V0.md`.
- No task has passed review, and no stage completion is claimed.
