# Smart Device Cloud & Automation Platform

- A modular monolith for practicing Python backend development. V1 provides Device registration and management, HTTP Telemetry ingestion, synchronous threshold Alerts, and manual TestTask lifecycle recording.
- Implemented foundations: FastAPI application factory, configuration, SQLAlchemy Session boundaries, reversible Alembic migrations, health checks, request IDs, unified errors, and JSON request logs.
- No authentication/authorization, automatic test runner, MQTT, message queues, configurable rule engine, frontend, or production deployment hardening. Use locally with trusted data; do not expose this unauthenticated learning service publicly.
- Responsibilities: the learner implements functionality; the assistant owns README, operating instructions, and pytest implementation, maintenance, and verification.
- Documentation is written in English. README updates are consolidated at major-stage completion; individual Task progress and review evidence belong in CURRENT_STAGE.md. V1 is a project stage, not a package version bump: APP_VERSION remains 0.1.0.

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

- The V1 unique head is `237c5f37c6c2`. The linear chain is `0001_v0_baseline` (no business tables) -> `f4502b63c0be` (devices) -> `438be65e5187` (telemetry) -> `68cc8b7ce48b` (alerts) -> `237c5f37c6c2` (test_tasks). Check `alembic heads` again before later-stage work.
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
python -m mypy .
python -m pip check
```

- PostgreSQL persistence, concurrency and migration tests skip without explicit opt-in; safe tests cover schema validation, isolated HTTP/service behavior, metadata and logging. A green safe run is not proof that real database acceptance passed. Current counts are in Section 10 and CURRENT_STAGE.md.
- Enable read-only probing separately. It loads `.env.test` and requires the test environment, a local host, the exact database name `smart_device_cloud_test`, the psycopg driver, and no URL query parameters. Connections enforce read-only transactions and timeouts; no schema is reset:

```bash
env -u RUN_MIGRATION_TESTS RUN_POSTGRES_SMOKE=1 python -m pytest -q -W error tests/integration/test_v0_smoke.py
```

- The following entry point is destructive: it may drop and recreate only local `smart_device_cloud_test.public`, removing all objects and data in that schema. Do not run services, other migrations, or other tests against that database concurrently.
- All four models and cross-module acceptance share target protection: local host, test environment, exact database name, psycopg driver, and no URL query parameters. Before resetting, they check the actual database name and reject other connected sessions. Ensure exclusive access, do not run parallel tests, and never permanently export the opt-in switch.
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

environment = dict(
    os.environ, RUN_MIGRATION_TESTS="1", RUN_POSTGRES_SMOKE="1",
    SETTINGS_FILE=".env.test",
)
subprocess.run(
    [
        sys.executable, "-m", "pytest", "-q", "-W", "error",
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

- This runs the entire suite, including four-model constraints, HTTP scenarios, transactional rollback, observed row-lock contention and the full migration chain. Do not edit `.env.test` during execution. Test-created rows are cleaned up; reset fixtures do not preserve prior test-schema contents. After successful acceptance, the test database must be at the unique head `237c5f37c6c2`.
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
  - This is historical evidence, not the current V1 result; see Section 10.
- Historical V0 verification:
  - Local date 2026-09-18: Ubuntu/WSL, Python 3.12.3, a new temporary venv, and fresh installation of the dev extra with pip download caching disabled.
  - The first rehearsal exposed the AnyIO 4.15 / Starlette 1.6 strict-warning incompatibility. After user approval, the dev constraint was added and installation was repeated in another new venv rather than reusing the failed environment.
  - The second startup rehearsal ran from UTC 2026-09-19 01:56:58 to 01:58:37.455, approximately 99.5 seconds. It included environment creation, installation, configuration loading, test-database upgrade, Uvicorn startup, six HTTP checks, graceful shutdown, and time between operations.
  - The repository, env files, database, and system software already existed; their preparation was excluded. A verified test-URL override and temporary local HTTP port protected the development database. Env files were not modified.
  - Clean-environment safe regression: 107 passed, 3 skipped. The separately enabled PostgreSQL smoke file reported 9 passed. Ruff lint/format, strict mypy, and pip check passed.
  - Both real migration tests passed after exact-target and other-session checks, resetting only the test schema. At that historical point, the database and unique repository head were `0001_v0_baseline`.
  - Health, readiness, versioned ping, docs, and OpenAPI returned 200; unversioned ping returned 404; shutdown was graceful. Migration round trips were verified separately and excluded from the second startup timing.
  - This is a local clean-Python-environment rehearsal, not proof of a literal fresh-machine installation. Original test-schema data was not retained.

## 9. V1 API and Business Demo

- All business paths below have the `/api/v1` prefix. See `/docs` and `/openapi.json` for field schemas and request examples.
- Device: POST `/devices` (201), GET `/devices` (200), GET/PATCH `/devices/{device_id}` (200). Serial numbers are unique and immutable. PATCH allows name/model/firmware_version/status; deactivation is irreversible in V1.
- Telemetry: POST `/devices/{device_id}/telemetry` (201), GET on the same path (200). Input requires metric, finite numeric value, unit and an aware ISO 8601 recorded_at; unit whitespace is trimmed. Device last_seen_at is a nondecreasing event-time watermark. Inactive Devices reject new samples with 409.
- Alert: GET `/alerts` (200), POST `/alerts/{alert_id}/acknowledge` and `/resolve` (200). Resolution works from open or acknowledged; repeated actions at the same state are idempotent. A resolved Alert cannot be acknowledged again (409).
- TestTask: POST `/test-tasks` (201), GET/PATCH `/test-tasks/{task_id}` (200). There is no task collection or delete endpoint. Creation requires an active Device, device_id and name; summary is optional. UUIDs/timestamps/status are not client-selectable at creation.
- Task transitions: pending -> running/cancelled; running -> passed/failed/cancelled. Terminal states cannot change to a different state. Same-state retries preserve lifecycle timestamps. PATCH permits only status and summary; omitted summary is preserved, null clears it, and summary-only edits work in all states. This records manual progress; it does not run a physical test.
- Device deactivation blocks new Telemetry and TestTasks but does not freeze existing Alert/Task operations. Writes use row locks and atomic transactions. There is no automatic Alert recovery, deduplication or task cancellation.
- Time fields are stored as timezone-aware instants and returned in UTC (`Z`). Telemetry recorded_at is device event time; received_at, Alert triggered_at and task lifecycle timestamps are platform times. They need not be equal.
- Collections return `{items, total, page, page_size}`. Page defaults to 1 (minimum 1); page_size defaults to 20 (1..100). Filters combine with AND; total is before pagination, and pages past the end have empty items. Default direction is desc; asc is also accepted, with id as a deterministic tie-breaker in the same direction.
  - Devices: exact status/model/serial_number filters; sort_by is created_at (default) or serial_number.
  - Telemetry: exact metric and inclusive aware from/to time filters on recorded_at; fixed recorded_at sort. Encode `+` in offset query values or use curl `--get --data-urlencode`; use `Z` for simple examples.
  - Alerts: exact device_id/status/severity/type filters; fixed triggered_at sort. An unknown Device filter returns an empty collection, not 404.
- Fixed synchronous threshold rules (metric and normalized unit must match exactly):
  - temperature / °C > 80 -> temperature_high, critical.
  - battery / % < 20 -> battery_low, warning.
  - signal_strength / dBm < -80 -> signal_weak, warning.
  - Equality does not trigger. Each breached sample creates a separate Alert, even if an earlier Alert is open/resolved; normal readings do not resolve Alerts. Sample, optional Alert and watermark commit together.
- Errors: malformed input 422, missing target 404, duplicate serial/inactive creation/forbidden transition 409; unexpected failures are sanitized 500. See Section 6 for the shared envelope and request ID.

### Copyable Bash demo

- Start the service and apply normal migrations first (Sections 4–5). The following requests write demo rows to the database selected by that running server. They do not reset or delete data. Confirm the server target before using them; an HTTP URL alone cannot tell you which database it uses.
- Run in the activated Python 3.12 environment. Only Python, Bash and curl are needed; no jq. The subshell exits on an unexpected HTTP status. Each execution generates a new serial; retrying POST registration with the same serial intentionally returns 409.
- To use a separately verified test-only server, set `V1_DEMO_BASE_URL` to its URL. Do not run destructive tests while that server holds database connections.
- Expected final state: one inactive Device, one temperature sample, one resolved critical Alert, one passed manual TestTask. The last two POSTs deliberately fail and add no rows.

```bash
# V1_DEMO_BEGIN
(
set -euo pipefail
demo_base="${V1_DEMO_BASE_URL:-http://127.0.0.1:8000}"
demo_serial="V1-$(python -c 'import uuid; print(uuid.uuid4().hex)')"
demo_body=''

demo_request() {
    local expected="$1" method="$2" path="$3" result actual
    local args=(-sS --connect-timeout 5 --max-time 15 -X "$method"
        -H 'X-Request-ID: v1-readme-demo' -w $'\n%{http_code}')
    if [ "$#" -eq 4 ]; then
        args+=(-H 'Content-Type: application/json' --data "$4")
    fi
    result=$(curl "${args[@]}" "$demo_base$path")
    actual="${result##*$'\n'}"
    demo_body="${result%$'\n'*}"
    printf '%s %s -> %s (expected %s)\n' "$method" "$path" "$actual" "$expected"
    if [ "$actual" != "$expected" ]; then
        printf '%s\n' "$demo_body"
        exit 1
    fi
}

demo_field() {
    printf '%s\n' "$demo_body" | python -c '
import json, sys
value = json.load(sys.stdin)
for part in sys.argv[1].split("."):
    value = value[int(part)] if isinstance(value, list) else value[part]
print(value)
' "$1"
}

demo_registration="{\"serial_number\":\"$demo_serial\",\"name\":\"Lab sensor\",\"model\":\"M1\",\"firmware_version\":\"1.0\"}"
demo_request 201 POST /api/v1/devices "$demo_registration"
demo_device=$(demo_field id)
demo_request 200 GET "/api/v1/devices/$demo_device"
demo_request 200 GET "/api/v1/devices?serial_number=$demo_serial"
test "$(demo_field total)" = 1

demo_sample='{"metric":"temperature","value":90,"unit":"°C","recorded_at":"2026-01-01T00:00:00Z"}'
demo_request 201 POST "/api/v1/devices/$demo_device/telemetry" "$demo_sample"
demo_request 200 GET "/api/v1/devices/$demo_device/telemetry?metric=temperature"
test "$(demo_field total)" = 1
demo_request 200 GET "/api/v1/alerts?device_id=$demo_device&type=temperature_high"
test "$(demo_field total)" = 1
test "$(demo_field items.0.status)" = open
test "$(demo_field items.0.severity)" = critical
demo_alert=$(demo_field items.0.id)
demo_request 200 POST "/api/v1/alerts/$demo_alert/acknowledge"
demo_request 200 POST "/api/v1/alerts/$demo_alert/resolve"
test "$(demo_field status)" = resolved
demo_resolved_at=$(demo_field resolved_at)
demo_request 200 POST "/api/v1/alerts/$demo_alert/resolve"
test "$(demo_field resolved_at)" = "$demo_resolved_at"

demo_task_body="{\"device_id\":\"$demo_device\",\"name\":\"Manual check\"}"
demo_request 201 POST /api/v1/test-tasks "$demo_task_body"
demo_task=$(demo_field id)
test "$(demo_field status)" = pending
demo_request 200 GET "/api/v1/test-tasks/$demo_task"
demo_request 200 PATCH "/api/v1/test-tasks/$demo_task" '{"status":"running"}'
demo_request 200 PATCH "/api/v1/test-tasks/$demo_task" '{"status":"passed","summary":"Manual check recorded"}'
test "$(demo_field status)" = passed
demo_finished_at=$(demo_field finished_at)
demo_request 200 PATCH "/api/v1/test-tasks/$demo_task" '{"status":"passed"}'
test "$(demo_field finished_at)" = "$demo_finished_at"

# Expected errors, not a failed demonstration.
demo_request 409 POST /api/v1/devices "$demo_registration"
demo_request 422 GET /api/v1/devices/not-a-uuid
demo_missing=$(python -c 'import uuid; print(uuid.uuid4())')
demo_request 404 GET "/api/v1/test-tasks/$demo_missing"
demo_request 409 PATCH "/api/v1/test-tasks/$demo_task" '{"status":"failed","summary":"Must not persist"}'
demo_request 200 GET "/api/v1/test-tasks/$demo_task"
test "$(demo_field summary)" = 'Manual check recorded'
demo_request 200 PATCH "/api/v1/devices/$demo_device" '{"status":"inactive"}'
demo_request 409 POST "/api/v1/devices/$demo_device/telemetry" "$demo_sample"
demo_request 409 POST /api/v1/test-tasks "$demo_task_body"
printf 'Demo completed: device=%s alert=%s task=%s\n' "$demo_device" "$demo_alert" "$demo_task"
)
# V1_DEMO_END
```

## 10. V1 Verification Evidence

- V1-T11 PASS on 2026-09-29 in the existing Ubuntu/WSL Python 3.12 environment. The older Section 8 snapshots are historical only.
- Safe regression with PostgreSQL opt-ins disabled: 492 passed, 76 skipped. Skips are not database acceptance evidence.
- Executed the exact guarded Section 7 entry point: 568 passed with warnings treated as errors and both PostgreSQL opt-ins enabled. This includes the two new cross-module scenarios, existing concurrency/rollback coverage and migration round trips.
- Final independent read-only verification confirmed `smart_device_cloud_test` with exactly one applied revision, `237c5f37c6c2`, matching the sole repository head.
- Whole-repository Ruff lint and formatting (80 files), `mypy .` (79 source files), dependency consistency and Git whitespace checks passed.
- Rehearsed the exact marked Section 9 Bash/curl demo against a temporary Uvicorn server on localhost:18765, constructed with explicit `.env.test` Settings after target validation. All 22 demo requests matched their expected statuses; persisted inactive Device, Telemetry, resolved Alert and passed TestTask state was independently verified.
- Live startup probes returned 200 for health, readiness, versioned ping, docs and OpenAPI, and 404 for unversioned ping. The server then shut down gracefully with exit code 0. The final full regression ran after shutdown.
- Destructive acceptance reset only the guarded test schema, including disposable demo data; prior test-schema contents were not preserved. No development/other database, env file, business implementation, migration or dependency was changed for T11.
- This was a local existing-environment rehearsal, not a new-machine installation, a fresh dependency installation, a measured startup benchmark, or hardware test execution. V2 and commit/push/tag were not performed.
