"""Acceptance tests for health, readiness, and database lifespan."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Engine
from starlette.testclient import TestClient

from app.api.health import get_session_factory
from app.core.config import Settings
from app.main import create_app


def test_health_returns_ok_without_database_access() -> None:
    app = create_app(Settings(database_url="sqlite+pysqlite:///:memory:"))
    dependency = MagicMock(side_effect=AssertionError("database accessed"))
    app.dependency_overrides[get_session_factory] = dependency

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    dependency.assert_not_called()


@pytest.mark.parametrize(
    ("available", "expected_code", "expected_status"),
    [(True, 200, "ready"), (False, 503, "not_ready")],
)
def test_ready_calls_probe_and_returns_exact_contract(
    available: bool, expected_code: int, expected_status: str
) -> None:
    app = create_app(Settings(database_url="sqlite+pysqlite:///:memory:"))
    factory = MagicMock()
    app.dependency_overrides[get_session_factory] = lambda: factory

    with patch(
        "app.api.health.check_database_readiness", return_value=available
    ) as probe:
        with TestClient(app) as client:
            response = client.get("/ready")

    assert response.status_code == expected_code
    assert response.json() == {"status": expected_status}
    probe.assert_called_once_with(factory)


def test_health_routes_are_unversioned_and_documented() -> None:
    app = create_app(Settings(database_url="sqlite+pysqlite:///:memory:"))
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
        for path in ("/health", "/ready"):
            assert "get" in paths[path]
            assert client.get("/api/v1" + path).status_code == 404
        assert "503" in paths["/ready"]["get"]["responses"]
        assert client.get("/api/v1/ping").json() == {"message": "pong"}


@pytest.mark.parametrize("raise_in_lifespan", [False, True])
def test_application_lifespan_owns_factory_and_disposes_engine(
    raise_in_lifespan: bool,
) -> None:
    app = create_app(Settings(database_url="sqlite+pysqlite:///:memory:"))
    with patch.object(Engine, "dispose", autospec=True) as dispose:
        try:
            with TestClient(app):
                factory = app.state.session_factory
                with factory() as first, factory() as second:
                    assert first is not second
                    engine = first.get_bind()
                    assert isinstance(engine, Engine)
                    assert second.get_bind() is engine
                dispose.assert_not_called()
                if raise_in_lifespan:
                    raise RuntimeError("lifespan test failure")
        except RuntimeError as exc:
            assert raise_in_lifespan
            assert str(exc) == "lifespan test failure"
        dispose.assert_called_once_with(engine)


def test_default_startup_uses_resolved_settings() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    with patch("app.main.get_settings", return_value=settings):
        app = create_app()
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200


def test_lifespan_disposes_engine_when_exception_enters_yield() -> None:
    """Exercise the lifespan context itself; TestClient body errors are different."""
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    engine = MagicMock(spec=Engine)
    app = create_app(settings)

    async def exercise_lifespan() -> None:
        with pytest.raises(RuntimeError, match="lifespan failure"):
            async with app.router.lifespan_context(app):
                raise RuntimeError("lifespan failure")

    with (
        patch("app.main.create_db_engine", return_value=engine),
        patch("app.main.create_session_factory"),
    ):
        asyncio.run(exercise_lifespan())

    engine.dispose.assert_called_once_with()


def test_lifespan_preserves_engine_creation_error() -> None:
    """An Engine that was never created must not be disposed."""
    app = create_app(Settings(database_url="sqlite+pysqlite:///:memory:"))
    error = RuntimeError("engine creation failed")

    async def exercise_lifespan() -> None:
        with pytest.raises(RuntimeError) as caught:
            async with app.router.lifespan_context(app):
                pytest.fail("startup should have failed")
        assert caught.value is error

    with patch("app.main.create_db_engine", side_effect=error):
        asyncio.run(exercise_lifespan())


def test_lifespan_disposes_engine_if_factory_initialization_fails() -> None:
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    engine = MagicMock(spec=Engine)
    app = create_app(settings)

    async def exercise_lifespan() -> None:
        with pytest.raises(RuntimeError, match="factory failure"):
            async with app.router.lifespan_context(app):
                pytest.fail("startup should have failed")

    with (
        patch("app.main.create_db_engine", return_value=engine),
        patch(
            "app.main.create_session_factory",
            side_effect=RuntimeError("factory failure"),
        ),
    ):
        asyncio.run(exercise_lifespan())

    engine.dispose.assert_called_once_with()
