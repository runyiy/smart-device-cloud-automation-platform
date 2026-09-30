"""V2-T1 transaction ownership and unexpected-error regression checks."""

from unittest.mock import MagicMock, call

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.transaction import transaction
from app.devices.service import DeviceNotFoundError


def test_context_commits_after_body_without_owning_session_lifecycle() -> None:
    session = MagicMock(spec=Session)
    with transaction(session):
        session.flush()
        session.commit.assert_not_called()
    assert session.mock_calls == [call.flush(), call.commit()]


@pytest.mark.parametrize("failure_at", ["body", "commit"])
@pytest.mark.parametrize("kind", ["domain", "unexpected", "database"])
def test_failure_rolls_back_once_and_preserves_exception(
    failure_at: str, kind: str
) -> None:
    session = MagicMock(spec=Session)
    error = {
        "domain": DeviceNotFoundError("missing"),
        "unexpected": RuntimeError("injected"),
        "database": OperationalError("statement", {}, Exception("injected")),
    }[kind]
    if failure_at == "commit":
        session.commit.side_effect = error
    with pytest.raises(type(error)) as caught:
        with transaction(session):
            if failure_at == "body":
                raise error
    assert caught.value is error
    expected = [call.rollback()]
    if failure_at == "commit":
        expected.insert(0, call.commit())
    assert session.mock_calls == expected
