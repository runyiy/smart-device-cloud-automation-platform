"""Acceptance tests for the database engine and Session lifecycle."""

from collections.abc import Generator
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_db_engine, create_session_factory, iter_db_session


def test_engine_uses_configured_url_and_pre_ping() -> None:
    """Engine construction should use the configured URL and stale-connection check."""
    database_url = (
        "postgresql+psycopg://smart_device_user:test-password@localhost:5432/"
        "smart_device_cloud_test"
    )
    settings = Settings(database_url=SecretStr(database_url))
    expected_engine = MagicMock(spec=Engine)

    with patch(
        "app.db.session.create_engine",
        return_value=expected_engine,
    ) as create_engine_mock:
        engine = create_db_engine(settings)

    assert engine is expected_engine
    create_engine_mock.assert_called_once_with(database_url, pool_pre_ping=True)


def test_session_factory_creates_independent_sessions() -> None:
    """Each factory call should return a distinct short-lived Session."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session_one, session_factory() as session_two:
            assert isinstance(session_one, Session)
            assert isinstance(session_two, Session)
            assert session_one is not session_two
            assert session_one.get_bind() is engine
            assert session_two.get_bind() is engine
    finally:
        engine.dispose()


def test_session_provider_closes_after_normal_iteration() -> None:
    """Exhausting the provider should close its Session."""
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    provider = iter_db_session(session_factory)

    assert next(provider) is session

    with pytest.raises(StopIteration):
        next(provider)

    session.close.assert_called_once()


def test_session_provider_closes_and_propagates_an_error() -> None:
    """An error sent into the provider should propagate after Session cleanup."""
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    provider = cast(
        Generator[Session, None, None],
        iter_db_session(session_factory),
    )

    assert next(provider) is session

    with pytest.raises(RuntimeError, match="boom"):
        provider.throw(RuntimeError("boom"))

    session.close.assert_called_once()


def test_session_provider_does_not_commit_implicitly() -> None:
    """Commit remains the responsibility of a later transaction boundary."""
    session = MagicMock(spec=Session)
    session_factory = MagicMock(return_value=session)
    provider = iter_db_session(session_factory)

    assert next(provider) is session

    with pytest.raises(StopIteration):
        next(provider)

    session.commit.assert_not_called()
    session.close.assert_called_once()
