# Smart Device Cloud & Automation Platform

- A modular monolith for practicing Python backend development. V0 is complete; V1-T1 adds the Device persistence model and migration, but no device business API yet.
- Implemented: FastAPI application factory, configuration, SQLAlchemy Session boundaries, Alembic migrations, health checks, request IDs, unified errors, and JSON request logs.
- Device business workflows, authentication, CRUD APIs, automation rules, message queues, and a frontend are not implemented yet.
- Responsibilities: the learner implements functionality; the assistant owns README, operating instructions, and pytest implementation, maintenance, and verification.
- Documentation is written in English. README functional updates are consolidated at the end of each major stage, starting with V1; individual Task progress belongs in CURRENT_STAGE.md. This translation is a user-requested exception to that schedule.

## 1. Prerequisites

- Run the following commands in Ubuntu / WSL Bash from the repository root.
- Install Python 3.12 (not 3.13), its venv support, Git, and curl, and have a running PostgreSQL service.
- Provision the two databases and login credentials beforehand:
  - Development: `smart_device_cloud`, with connection and schema privileges needed for migrations.
  - Test: `smart_device_cloud_test`, containing disposable test data only. Destructive migration acceptance also requires permission to drop and recreate its `public` schema.
  - This project uses the existing databases. Do not recreate them or use `music_ai_db` or another database.
- On a new machine, PostgreSQL installation and account/database provisioning are prerequisites. This guide does not perform those administrative operations automatically.
- The 15-minute startup target begins after prerequisites and checkout are ready. It includes virtual environment creation, dependency installation, configuration, migration, startup, and HTTP checks, but excludes OS, Python, and PostgreSQL installation. See the evidence section for actual rehearsal scope and timing.

## 2. Installation

- Clone only if you do not already have the repository; otherwise enter the existing checkout:

```bash
git clone https://github.com/runyiy/smart-device-cloud-automation-platform.git
cd smart-device-cloud-automation-platform
```

- Create the virtual environment on first use; skip creation if a suitable Python 3.12 environment already exists:

```bash
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pip check
```

- In subsequent terminals, enter the repository and activate `.venv` again.
- Dependencies are declared in `pyproject.toml`. There is no lockfile, so installations at different times may resolve different compatible versions.
- The dev extra temporarily constrains AnyIO to `>=4.14.2,<4.15`: a verified Starlette 1.6 TestClient / AnyIO 4.15 combination raises a deprecation warning during strict test collection. Warnings are not suppressed; revisit this constraint after upstream compatibility is verified.

## 3. Configuration

- Copy templates only for missing files; preserve existing configuration:

```bash
test -e .env || cp .env.example .env
test -e .env.test || cp .env.example .env.test
```

- Edit both files locally with your existing credentials. Never paste passwords into logs, commits, or screenshots.
- Example database configuration for `.env`; replace the password placeholder:

```dotenv
ENVIRONMENT=development
DATABASE_URL=postgresql+psycopg://smart_device_user:YOUR_PASSWORD@localhost:5432/smart_device_cloud
```

- Example database configuration for `.env.test`:

```dotenv
ENVIRONMENT=test
DATABASE_URL=postgresql+psycopg://smart_device_user:YOUR_PASSWORD@localhost:5432/smart_device_cloud_test
```

- Percent-encode URL-special characters in passwords. Do not print complete connection strings for troubleshooting.
- Supported settings:
  - `APP_NAME`: defaults to `Smart Device Cloud & Automation Platform`.
  - `APP_VERSION`: defaults to `0.1.0`.
  - `ENVIRONMENT`: `development` or `test`; defaults to development.
  - `DEBUG`: defaults to `false`.
  - `DATABASE_URL`: required; use the `postgresql+psycopg` driver.
- Process environment variables override env files; explicitly supplied Settings fields take higher priority. Restart the service after configuration changes to avoid cached settings.
- The application factory defaults to `.env`. Only Alembic uses `SETTINGS_FILE` to select a file. Setting `ENVIRONMENT=test` alone does not select `.env.test`.
- Git ignores `.env` and `.env.test`. Commit only the credential-free `.env.example` template.

## 4. Migrations

- Inspect repository revisions without connecting to a database:

```bash
python -m alembic heads
python -m alembic history
```

- At the V1-T1 verification snapshot, the unique head is `f4502b63c0be`, which adds `devices`. Its predecessor, `0001_v0_baseline`, is the table-free V0 baseline. Use `alembic heads` for the current revision during ongoing stage work.
- The first command below reads the development database revision; the second modifies the database selected by `.env`. First confirm that it targets the existing `smart_device_cloud` database. Perform only normal upgrades here, never a development schema reset or downgrade:

```bash
env -u DATABASE_URL -u ENVIRONMENT SETTINGS_FILE=.env python -m alembic current
env -u DATABASE_URL -u ENVIRONMENT SETTINGS_FILE=.env python -m alembic upgrade head
```

- The two migration acceptance tests in Section 7 cover the test-only `upgrade head -> downgrade base -> upgrade head` cycle.
- `downgrade base` reverses all migrations. It is not a general repair command for unknown database states. Run it only against an explicitly authorized disposable test database, never by copying it into development operations.

## 5. Start and Inspect the Service

- Development startup defaults to `.env`. Clear stale process-level database overrides before starting. `--no-access-log` disables independent Uvicorn access logging while retaining application JSON request logs:

```bash
env -u DATABASE_URL -u ENVIRONMENT python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

- In another terminal, run:

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
curl -i -H 'X-Request-ID: local-check-001' http://127.0.0.1:8000/api/v1/ping
curl -i http://127.0.0.1:8000/ping
curl -i http://127.0.0.1:8000/docs
curl -i http://127.0.0.1:8000/openapi.json
```

- Expected results:
  - `/health`: 200, `{"status":"ok"}`; this does not prove database availability.
  - `/ready`: executes a real database probe; 200 with `{"status":"ready"}` when available, or 503 with `{"status":"not_ready"}` otherwise.
  - `/api/v1/ping`: 200, `{"message":"pong"}`; the response header echoes `local-check-001`.
  - `/ping`: 404; ping is mounted only under the versioned API path.
  - `/docs`: 200 HTML. Open it in a browser for Swagger UI; loading its frontend assets may require internet access.
  - `/openapi.json`: 200 OpenAPI JSON.
- Stop the service with Ctrl+C in its terminal so lifespan cleanup disposes the database engine.
- You may add `--reload` for development. Automatic reload is not a production deployment configuration.

## 6. Request IDs, Errors, and Logging

- Accept exactly one incoming `X-Request-ID`, 1–64 characters long, using only ASCII letters, digits, dots, underscores, and hyphens: `[A-Za-z0-9._-]{1,64}`.
- Valid examples: `demo-001`, `abc_DEF.9`. Empty values, spaces, non-ASCII characters, commas, duplicate headers, and overlong values are invalid.
- Missing or invalid IDs do not reject the request. The application generates a new UUID hex ID and uses the same ID in the response header, error envelope, and request log.
- Example 404 response; the ID may differ for each request:

```json
{"error":{"code":"HTTP_404","message":"Not Found","request_id":"local-check-001"}}
```

- HTTP errors retain their status without echoing exception details. Validation errors use `VALIDATION_ERROR`; unexpected exceptions use `INTERNAL_ERROR`. Readiness 503 responses keep their dedicated health-check format.
- `app.requests` emits one JSON line per request containing `timestamp`, `level`, `event`, `request_id`, `method`, `route`, `status_code`, and `duration_ms`.
- `route` contains the route template, or `<unmatched>` for unmatched requests. Logs do not collect query parameters, request bodies, authentication headers, database URLs, or exception tracebacks.
- This policy covers application request logs only; it does not claim that independent Uvicorn or third-party logs use the same sanitization.

## 7. Verification

- Routine safe checks do not enable schema resets. Explicitly unset database opt-in switches:

```bash
env -u RUN_MIGRATION_TESTS -u RUN_POSTGRES_SMOKE python -m pytest -q -W error
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pip check
```

- At the V1-T1 snapshot, seven tests skip by default: two real migration tests, four Device database acceptance tests, and one read-only PostgreSQL smoke test. Logging, Docs/OpenAPI, and Device metadata checks run by default. Task-level test counts are recorded in CURRENT_STAGE.md.
- Enable read-only probing separately. It loads `.env.test` and requires the test environment, a local host, the exact database name `smart_device_cloud_test`, the psycopg driver, and no URL query parameters. Connections enforce read-only transactions and timeouts; no schema is reset:

```bash
env -u RUN_MIGRATION_TESTS RUN_POSTGRES_SMOKE=1 python -m pytest -q -W error tests/integration/test_v0_smoke.py
```

- The following entry point is destructive: it may drop and recreate only local `smart_device_cloud_test.public`, removing all objects and data in that schema. Do not run services, other migrations, or other tests against that database concurrently.
- Migration and Device acceptance share target protection: local host, test environment, exact database name, psycopg driver, and no URL query parameters. Before resetting, they check the actual database name and reject other connected sessions. Ensure exclusive access, do not run parallel tests, and never permanently export the opt-in switch.
- Run this only after confirming that the test data is disposable. It does not operate on the development database:

```bash
env -u DATABASE_URL -u ENVIRONMENT python - <<'PY'
import os
import subprocess
import sys

from sqlalchemy.engine import make_url

from app.core.config import Environment, Settings

settings = Settings(_env_file=".env.test")
url = make_url(settings.database_url.get_secret_value())
if (
    settings.environment is not Environment.TEST
    or url.drivername != "postgresql+psycopg"
    or url.host not in {"localhost", "127.0.0.1"}
    or url.database != "smart_device_cloud_test"
    or url.query
):
    raise SystemExit("STOP: test database target is outside the authorized scope")

environment = dict(os.environ, RUN_MIGRATION_TESTS="1", SETTINGS_FILE=".env.test")
subprocess.run(
    [
        sys.executable, "-m", "pytest", "-q", "-W", "error",
        "tests/integration/test_migrations.py",
        "tests/integration/test_devices.py",
    ],
    env=environment,
    check=True,
)
subprocess.run(
    [sys.executable, "-m", "alembic", "current"],
    env=environment,
    check=True,
)
PY
```

- Do not edit `.env.test` during execution. At the V1-T1 snapshot, these files produce 14 passed, covering target protection, empty-database upgrades, head -> V0 baseline -> head, full base/head round trips, Device defaults, constraints, timezones, schema consistency, and concurrent uniqueness. The final revision is the unique head `f4502b63c0be`; test-created Device rows are cleaned up.
- If a test fails, preserve the error and inspect the target database and revision. Do not reset another database as a workaround.

## 8. Troubleshooting and Evidence Boundaries

- Python or driver mismatch: confirm that the active `.venv` uses Python 3.12; reinstall the dev extra and run `pip check`. Do not arbitrarily replace the PostgreSQL driver.
- Missing `DATABASE_URL`: confirm the repository-root working directory, configuration file, and required field. Do not print the complete configuration.
- Env-file changes have no effect: check process overrides and cached settings, then restart. Do not start the application with `SETTINGS_FILE=.env.test` and assume it selects test configuration.
- `/health` succeeds but `/ready` returns 503: check PostgreSQL service availability, host, credentials, database name, and privileges. Application startup does not mean a database connection has already succeeded.
- Migration revision mismatch: compare the correct target's `alembic current` with repository `heads/history`. Do not use `stamp` or schema deletion to hide unknown differences.
- Migration tests skipped by default: this is intentional protection, not evidence that PostgreSQL acceptance passed. Use the separate guarded entry point.
- Retained V1-T1 verification snapshot (2026-09-23):
  - Safe regression: 111 passed, 7 skipped. Migration/Device acceptance enabled separately: 14 passed.
  - Both database acceptance and read-only smoke enabled on the exclusively used authorized test database: 118 passed, no skips.
  - Ruff lint/format, strict mypy (33 files), and pip check passed. Database and repository heads both matched f4502b63c0be.
  - Only smart_device_cloud_test.public was recreated. No other database or application model/migration implementation was changed by that test-update work.
  - This existing snapshot is retained during translation; subsequent Task updates are recorded in CURRENT_STAGE.md until V1 completes.
- Historical V0 verification:
  - Local date 2026-09-18: Ubuntu/WSL, Python 3.12.3, a new temporary venv, and fresh installation of the dev extra with pip download caching disabled.
  - The first rehearsal exposed the AnyIO 4.15 / Starlette 1.6 strict-warning incompatibility. After user approval, the dev constraint was added and installation was repeated in another new venv rather than reusing the failed environment.
  - The second startup rehearsal ran from UTC 2026-09-19 01:56:58 to 01:58:37.455, approximately 99.5 seconds. It included environment creation, installation, configuration loading, test-database upgrade, Uvicorn startup, six HTTP checks, graceful shutdown, and time between operations.
  - The repository, env files, database, and system software already existed; their preparation was excluded. A verified test-URL override and temporary local HTTP port protected the development database. Env files were not modified.
  - Clean-environment safe regression: 107 passed, 3 skipped. The separately enabled PostgreSQL smoke file reported 9 passed. Ruff lint/format, strict mypy, and pip check passed.
  - Both real migration tests passed after exact-target and other-session checks, resetting only the test schema. At that historical point, the database and unique repository head were `0001_v0_baseline`.
  - Health, readiness, versioned ping, docs, and OpenAPI returned 200; unversioned ping returned 404; shutdown was graceful. Migration round trips were verified separately and excluded from the second startup timing.
  - This is a local clean-Python-environment rehearsal, not proof of a literal fresh-machine installation. Original test-schema data was not retained.
