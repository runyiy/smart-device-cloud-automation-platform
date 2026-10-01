"""User persistence queries on the caller-owned Session."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.users.model import User


class UserRepository:
    """No Session finalization, credential processing or authorization decisions."""

    def __init__(self, session: Session) -> None:
        """Retain the exact caller-owned Session."""
        self.session = session

    def add(self, user: User) -> None:
        """Stage a supplied User without committing or hashing."""
        self.session.add(user)

    def get(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        """Look up an ID, optionally locking and reloading current values.

        Return None when absent. Leave lock lifetime to the caller's transaction.
        """
        if for_update:
            stmt = (
                select(User)
                .where(User.id == user_id)
                .with_for_update()
                # Reload cached attributes before the caller makes a decision.
                .execution_options(populate_existing=True)
            )
        else:
            stmt = select(User).where(User.id == user_id)

        user = self.session.scalar(stmt)
        return user

    def get_by_email(self, normalized_email: str) -> User | None:
        """Perform an exact nonlocking lookup without normalization."""
        stmt = select(User).where(User.email == normalized_email)

        user = self.session.scalar(stmt)

        return user

    def refresh(self, user: User) -> None:
        """Reload persisted values without finalizing the transaction."""
        self.session.refresh(user)
