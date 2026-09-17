"""Minimal PostgreSQL readiness probe."""

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, TimeoutError

from app.db.session import SessionFactory


def check_database_readiness(session_factory: SessionFactory) -> bool:
    """Return whether a short-lived Session can execute the readiness query."""
    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))

        return True
    except (OperationalError, TimeoutError):
        return False
