"""Synchronous transaction finalization for a complete write use case."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def transaction(session: Session) -> Iterator[None]:
    """Commit once on success; roll back body or commit exceptions and re-raise.

    The caller owns the Session exclusively for this use case, including any
    prerequisite reads and their autobegin transaction. Do not nest this context
    or combine it with an outer transaction owner or unrelated pending writes.
    This helper never starts a savepoint or closes the Session. Read-only use
    cases do not use this committing context.
    """
    try:
        yield
        session.commit()
    except Exception:
        session.rollback()
        raise
