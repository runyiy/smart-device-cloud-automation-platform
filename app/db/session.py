"""SQLAlchemy engine and short-lived Session construction."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

SessionFactory = sessionmaker[Session]


def create_db_engine(settings: Settings) -> Engine:
    """Create the process-level SQLAlchemy engine from validated settings."""
    database_url = settings.database_url.get_secret_value()

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
    )

    return engine


def create_session_factory(engine: Engine) -> SessionFactory:
    """Create the Session factory bound to one engine."""
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    return session_factory


def iter_db_session(session_factory: SessionFactory) -> Iterator[Session]:
    """Yield one Session and always close it without committing implicitly."""
    db = session_factory()

    try:
        yield db
    finally:
        db.close()
