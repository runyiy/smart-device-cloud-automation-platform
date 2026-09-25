"""Request Session cleanup without a database connection."""

from collections.abc import Generator
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session


@pytest.mark.parametrize("failure", [False, True])
def test_request_dependency_closes_but_never_commits(failure: bool) -> None:
    request = MagicMock(spec=Request)
    session = MagicMock(spec=Session)
    request.app.state.session_factory.return_value = session
    dependency = cast(
        Generator[Session, None, None], get_db_session(cast(Request, request))
    )
    assert next(dependency) is session
    if failure:
        with pytest.raises(RuntimeError, match="request failure"):
            dependency.throw(RuntimeError("request failure"))
    else:
        with pytest.raises(StopIteration):
            next(dependency)
    session.close.assert_called_once()
    session.commit.assert_not_called()
