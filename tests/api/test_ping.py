"""Acceptance tests for the application factory and versioned ping route."""

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_create_app_uses_injected_metadata() -> None:
    """The factory should expose title, version, and debug from injected settings."""

    settings = Settings(
        app_name="Test Application",
        app_version="9.9.9",
        debug=True,
        database_url=SecretStr("postgresql://test:test@localhost/test_db"),
    )

    app = create_app(settings)

    assert app.title == "Test Application"
    assert app.version == "9.9.9"
    assert app.debug is True


def test_create_app_uses_get_settings_when_settings_not_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_settings = Settings(
        app_name="Test Application",
        app_version="9.9.9",
        database_url=SecretStr("postgresql://test:test@localhost/test_db"),
    )

    def fake_get_settings() -> Settings:
        return test_settings

    monkeypatch.setattr("app.main.get_settings", fake_get_settings)

    app = create_app()

    assert app.title == "Test Application"
    assert app.version == "9.9.9"


def test_create_app_returns_independent_app_instances() -> None:
    settings = Settings(
        database_url="postgresql://test:test@localhost:5432/test_db",
    )

    first_app = create_app(settings)
    second_app = create_app(settings)

    assert first_app is not second_app


def test_versioned_ping_returns_exact_contract() -> None:
    """GET /api/v1/ping should return HTTP 200 and the pong response."""
    settings = Settings(
        database_url="postgresql://test:test@localhost/test_db",
    )

    app = create_app(settings)
    client = TestClient(app)

    responses = client.get("/api/v1/ping")

    assert responses.status_code == 200
    assert responses.json() == {"message": "pong"}


def test_unversioned_ping_is_not_registered() -> None:
    """The ping endpoint should only exist below the versioned API prefix."""

    settings = Settings(
        database_url="postgresql://test:test@localhost/test_db",
    )

    app = create_app(settings)
    client = TestClient(app)

    responses = client.get("/ping")

    assert responses.status_code == 404


def test_openapi_contains_the_versioned_ping_operation() -> None:
    """The generated schema should document the public ping operation."""

    settings = Settings(
        database_url="postgresql://test:test@localhost/test_db",
    )

    app = create_app(settings)
    client = TestClient(app)

    responses = client.get("/openapi.json")

    assert responses.status_code == 200

    schema = responses.json()

    assert "/api/v1/ping" in schema["paths"]
    assert "get" in schema["paths"]["/api/v1/ping"]
