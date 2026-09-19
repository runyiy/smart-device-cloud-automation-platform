"""Acceptance tests for correlation and safe API errors."""

import logging
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from app.api.health import get_session_factory
from app.core.config import Settings
from app.main import create_app


class RecordCollector(logging.Handler):
    def __init__(self, records: list[logging.LogRecord]) -> None:
        super().__init__()
        self.records = records

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def records() -> Iterator[list[logging.LogRecord]]:
    """Isolate routing tests from formatter defects, tested separately."""
    collected: list[logging.LogRecord] = []
    saved = []
    for name in ("app.requests", "app.request"):
        logger = logging.getLogger(name)
        saved.append((logger, logger.handlers[:], logger.level, logger.propagate))
        logger.handlers = [RecordCollector(collected)]
        logger.setLevel(logging.INFO)
        logger.propagate = False
    try:
        with patch("app.main.configure_request_logging"):
            yield collected
    finally:
        for logger, handlers, level, propagate in saved:
            logger.handlers = handlers
            logger.setLevel(level)
            logger.propagate = propagate


@pytest.fixture
def app(records: list[logging.LogRecord]) -> FastAPI:
    application = create_app(Settings(database_url="sqlite+pysqlite:///:memory:"))

    @application.get("/test/value")
    def value(count: int) -> dict[str, int]:
        return {"count": count}

    @application.get("/test/auth")
    def auth() -> None:
        raise HTTPException(
            401,
            detail="PRIVATE_SECRET",
            headers={
                "WWW-Authenticate": "Bearer",
                "Content-Type": "text/plain",
                "Content-Length": "1",
                "X-Request-ID": "wrong",
            },
        )

    @application.get("/test/crash")
    def crash() -> None:
        raise RuntimeError("PRIVATE_SECRET")

    return application


def test_valid_request_id_round_trips(app: FastAPI) -> None:
    with TestClient(app) as client:
        r = client.get("/health", headers={"X-Request-ID": "client_123.A-b"})
    assert r.headers["X-Request-ID"] == "client_123.A-b"


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("X-Request-ID", "")],
        [("X-Request-ID", "bad id")],
        [("X-Request-ID", "a" * 65)],
        [("X-Request-ID", "one"), ("X-Request-ID", "two")],
    ],
)
def test_invalid_or_missing_ids_are_replaced(
    app: FastAPI, headers: list[tuple[str, str]]
) -> None:
    with TestClient(app) as client:
        first = client.get("/health", headers=headers)
        second = client.get("/health", headers=headers)
    first_id = first.headers["X-Request-ID"]
    assert len(first_id) == 32
    assert UUID(hex=first_id).version == 4
    assert first_id != second.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("method", "path", "status_code", "code", "message"),
    [
        ("GET", "/missing", 404, "HTTP_404", "Not Found"),
        ("POST", "/health", 405, "HTTP_405", "Method Not Allowed"),
        ("GET", "/test/auth", 401, "HTTP_401", "Unauthorized"),
        (
            "GET",
            "/test/value?count=PRIVATE_SECRET",
            422,
            "VALIDATION_ERROR",
            "Request validation failed",
        ),
    ],
)
def test_error_contract(
    app: FastAPI, method: str, path: str, status_code: int, code: str, message: str
) -> None:
    with TestClient(app) as client:
        r = client.request(method, path)
    assert r.status_code == status_code
    assert r.json() == {
        "error": {
            "code": code,
            "message": message,
            "request_id": r.headers["X-Request-ID"],
        }
    }
    assert "PRIVATE_SECRET" not in r.text
    assert r.headers["content-type"].startswith("application/json")
    assert int(r.headers["content-length"]) == len(r.content)
    if status_code == 405:
        assert "GET" in r.headers["allow"]
    if status_code == 401:
        assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("debug", [False, True])
def test_unexpected_error_is_safe(app: FastAPI, debug: bool) -> None:
    app.debug = debug
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/test/crash")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error",
            "request_id": r.headers["X-Request-ID"],
        }
    }
    assert "PRIVATE_SECRET" not in r.text


def test_concurrent_ids_and_one_log_per_request(
    app: FastAPI, records: list[logging.LogRecord]
) -> None:
    ids = [f"parallel-{i}" for i in range(8)]
    with TestClient(app) as client:

        def request(request_id: str) -> str:
            return client.get("/health", headers={"X-Request-ID": request_id}).headers[
                "X-Request-ID"
            ]

        with ThreadPoolExecutor(max_workers=4) as executor:
            assert list(executor.map(request, ids)) == ids
    assert len(records) == len(ids)
    assert {getattr(r, "request_id", None) for r in records} == set(ids)
    assert all(r.name == "app.requests" for r in records)


def test_log_uses_template_and_required_event(
    app: FastAPI, records: list[logging.LogRecord]
) -> None:
    with TestClient(app) as client:
        client.get("/unknown/PRIVATE_SECRET?token=PRIVATE_SECRET")
    assert len(records) == 1
    record = records[0]
    assert record.name == "app.requests"
    assert getattr(record, "route", None) == "<unmatched>"
    assert getattr(record, "status_code", None) == 404
    assert getattr(record, "duration_ms", -1) >= 0
    assert "PRIVATE_SECRET" not in str(record.__dict__)


@pytest.mark.parametrize(
    ("status_code", "message"),
    [(code.value, code.phrase) for code in HTTPStatus if code.value >= 400]
    + [(499, "HTTP error"), (599, "HTTP error")],
)
def test_other_http_status_messages(
    app: FastAPI, status_code: int, message: str
) -> None:
    @app.get("/test/status")
    def fail() -> None:
        raise HTTPException(status_code, detail="PRIVATE_SECRET")

    with TestClient(app) as client:
        response = client.get("/test/status")
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == f"HTTP_{status_code}"
    assert response.json()["error"]["message"] == message


@pytest.mark.parametrize(
    ("status_code", "header_name", "header_value"),
    [
        (401, "www-authenticate", "Bearer"),
        (405, "aLlOw", "GET"),
        (429, "Retry-After", "60"),
    ],
)
def test_protocol_headers_are_preserved_case_insensitively(
    app: FastAPI, status_code: int, header_name: str, header_value: str
) -> None:
    @app.get("/test/protocol")
    def fail() -> None:
        raise HTTPException(status_code, headers={header_name: header_value})

    with TestClient(app) as client:
        response = client.get("/test/protocol")
    assert response.status_code == status_code
    assert response.headers.get(header_name) == header_value


def test_existing_readiness_contract(app: FastAPI) -> None:
    app.dependency_overrides[get_session_factory] = lambda: object()
    with patch("app.api.health.check_database_readiness", return_value=False):
        with TestClient(app) as client:
            r = client.get("/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready"}
    assert r.headers["X-Request-ID"]
