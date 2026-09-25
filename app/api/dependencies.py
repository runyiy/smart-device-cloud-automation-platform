"""Request-scoped Sessions from the application-owned factory."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.session import iter_db_session


def get_db_session(request: Request) -> Iterator[Session]:
    """Yield a fresh Session from the lifespan-owned factory and always close it."""
    # Do not create an Engine, keep a global Session, or commit in this dependency.
    yield from iter_db_session(request.app.state.session_factory)
