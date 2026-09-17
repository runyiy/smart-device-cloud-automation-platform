"""Tests for the read-only readiness probe and its resource boundary."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError, TimeoutError
from sqlalchemy.orm import Session

from app.db.readiness import check_database_readiness


def test_readiness_probe_executes_select_one_and_releases_each_session() -> None:
    first = MagicMock(spec=Session)
    second = MagicMock(spec=Session)
    for session in (first, second):
        session.__enter__.return_value = session
    factory = MagicMock(side_effect=[first, second])

    assert check_database_readiness(factory) is True
    assert check_database_readiness(factory) is True

    assert factory.call_count == 2
    for session in (first, second):
        session.execute.assert_called_once()
        assert str(session.execute.call_args.args[0]).strip().upper() == "SELECT 1"
        session.commit.assert_not_called()
        session.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("private connection detail")),
        TimeoutError("connection pool exhausted"),
    ],
)
def test_readiness_probe_returns_false_and_releases_session(error: Exception) -> None:
    session = MagicMock(spec=Session)
    session.__enter__.return_value = session
    session.execute.side_effect = error
    factory = MagicMock(return_value=session)

    assert check_database_readiness(factory) is False

    factory.assert_called_once_with()
    session.__exit__.assert_called_once()
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("unexpected bug"),
        ProgrammingError("invalid query", {}, Exception("programming bug")),
    ],
)
def test_readiness_probe_propagates_programming_errors(error: Exception) -> None:
    session = MagicMock(spec=Session)
    session.__enter__.return_value = session
    session.execute.side_effect = error
    factory = MagicMock(return_value=session)

    with pytest.raises(type(error)) as caught:
        check_database_readiness(factory)

    assert caught.value is error
    session.__exit__.assert_called_once()
    session.commit.assert_not_called()
