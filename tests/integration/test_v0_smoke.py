"""V0 acceptance checks; only the explicit PostgreSQL smoke uses a real database."""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.engine import make_url
from starlette.testclient import TestClient

from app.core.config import Environment, Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
POSTGRES_OPT_IN = "RUN_POSTGRES_SMOKE"


def exercise_real_logging() -> None:
    """Run only in a child process so no pytest logger replacement can interfere."""
    settings = Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:")
    results = []
    for iteration in range(2):
        app = create_app(settings)

        @app.get("/test/auth")
        def auth() -> None:
            raise HTTPException(401, detail="PRIVATE_SECRET")

        @app.get("/test/crash")
        def crash() -> None:
            raise RuntimeError("PRIVATE_SECRET")

        @app.get("/test/value")
        def value(count: int) -> dict[str, int]:
            return {"count": count}

        cases = [
            ("/health", 200, "/health", None),
            ("/missing/PRIVATE_SECRET", 404, "<unmatched>", "HTTP_404"),
            ("/test/auth", 401, "/test/auth", "HTTP_401"),
            ("/test/crash", 500, "/test/crash", "INTERNAL_ERROR"),
            (
                "/test/value?count=PRIVATE_SECRET",
                422,
                "/test/value",
                "VALIDATION_ERROR",
            ),
        ]
        with TestClient(app, raise_server_exceptions=False) as client:
            for index, (path, status, route, code) in enumerate(cases):
                request_id = f"smoke-{iteration}-{index}"
                response = client.get(
                    path,
                    headers={
                        "X-Request-ID": request_id,
                        "Authorization": "Bearer PRIVATE_SECRET",
                    },
                )
                assert response.status_code == status
                assert response.headers["X-Request-ID"] == request_id
                assert "PRIVATE_SECRET" not in response.text
                if code is not None:
                    error = response.json()["error"]
                    assert error["code"] == code
                    assert error["request_id"] == request_id
                else:
                    assert response.json() == {"status": "ok"}
                results.append(
                    {"request_id": request_id, "status_code": status, "route": route}
                )
        assert len(logging.getLogger("app.requests").handlers) == 1
    print(json.dumps(results))


def test_http_contracts_and_real_json_logs_in_isolated_process() -> None:
    """Exercise real middleware and formatter together, including repeat creation."""
    result = subprocess.run(
        [sys.executable, "-W", "error", "-m", "tests.integration.test_v0_smoke"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert "PRIVATE_SECRET" not in result.stdout + result.stderr
    expected = json.loads(result.stdout)
    records = [json.loads(line) for line in result.stderr.splitlines()]
    assert len(records) == len(expected) == 10
    for record, response in zip(records, expected, strict=True):
        assert set(record) == {
            "timestamp",
            "level",
            "event",
            "request_id",
            "method",
            "route",
            "status_code",
            "duration_ms",
        }
        for field in ("request_id", "status_code", "route"):
            assert record[field] == response[field]
        assert record["event"] == "http_request"
        assert record["method"] == "GET"
        assert record["level"] == (
            "ERROR" if response["status_code"] == 500 else "INFO"
        )
        assert isinstance(record["duration_ms"], (int, float))
        assert record["duration_ms"] >= 0
        assert datetime.fromisoformat(record["timestamp"]).utcoffset() == timedelta(0)


def test_openapi_and_docs_are_available() -> None:
    """Use the real app factory without requiring a PostgreSQL connection."""
    settings = Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:")
    with TestClient(create_app(settings)) as client:
        docs = client.get("/docs")
        assert docs.status_code == 200
        assert docs.headers["content-type"].startswith("text/html")
        assert "/openapi.json" in docs.text
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == settings.app_name
        assert schema["info"]["version"] == settings.app_version
        assert set(schema["paths"]) == {
            "/health",
            "/ready",
            "/api/v1/ping",
            "/api/v1/devices",
            "/api/v1/devices/{device_id}",
        }
        assert "503" in schema["paths"]["/ready"]["get"]["responses"]


def validate_smoke_target(settings: Settings) -> None:
    """Reject other databases and query parameters that could redirect libpq."""
    url = make_url(settings.database_url.get_secret_value())
    if (
        settings.environment is not Environment.TEST
        or url.drivername != "postgresql+psycopg"
        or url.host not in {"localhost", "127.0.0.1"}
        or url.database != "smart_device_cloud_test"
        or url.query
    ):
        raise ValueError("PostgreSQL smoke target is outside the authorized scope")


@pytest.mark.parametrize(
    ("environment", "url"),
    [
        ("development", "postgresql+psycopg://localhost/smart_device_cloud_test"),
        ("test", "postgresql+psycopg://localhost/smart_device_cloud"),
        ("test", "postgresql+psycopg://localhost/other_test"),
        ("test", "postgresql+psycopg://remote/smart_device_cloud_test"),
        ("test", "postgresql://localhost/smart_device_cloud_test"),
        ("test", "postgresql+psycopg://localhost/smart_device_cloud_test?host=remote"),
    ],
)
def test_postgres_smoke_rejects_unsafe_targets(environment: str, url: str) -> None:
    settings = Settings(_env_file=None, environment=environment, database_url=url)
    with pytest.raises(ValueError, match="outside the authorized scope"):
        validate_smoke_target(settings)


def test_readiness_uses_explicit_test_postgres_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opt in separately; use read-only PostgreSQL sessions and bounded queries."""
    if os.getenv(POSTGRES_OPT_IN) != "1":
        pytest.skip(f"set {POSTGRES_OPT_IN}=1 for read-only PostgreSQL smoke")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    settings = Settings(_env_file=ROOT / ".env.test")
    validate_smoke_target(settings)
    url = make_url(settings.database_url.get_secret_value()).update_query_dict(
        {
            "options": "-c default_transaction_read_only=on -c statement_timeout=5000",
            "connect_timeout": "5",
        }
    )
    readonly_settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url=url.render_as_string(hide_password=False),
    )
    with TestClient(create_app(readonly_settings)) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
        assert response.headers["X-Request-ID"]


if __name__ == "__main__":
    exercise_real_logging()
