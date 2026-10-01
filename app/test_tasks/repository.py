"""TestTask persistence queries on a caller-owned Session.

Business rules belong to Services; write finalization belongs to the existing
use-case transaction boundary. Reads and refresh never finalize transactions.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.test_tasks.model import TestTask


class TestTaskRepository:
    """Never create, commit, roll back, or close a Session."""

    def __init__(self, session: Session) -> None:
        """Retain the exact supplied Session without opening resources."""
        self.session = session

    def add(self, test_task: TestTask) -> None:
        """Stage the supplied task; leave finalization to the caller."""
        self.session.add(test_task)

    def get(self, task_id: UUID, *, for_update: bool = False) -> TestTask | None:
        """Return a task or None, optionally locking and reloading its current state.

        Hold any lock until the caller ends the transaction. Do not load the
        Device relationship or apply lifecycle rules.
        """
        if for_update:
            stmt = (
                select(TestTask)
                .where(TestTask.id == task_id)
                .with_for_update()
                # FOR UPDATE locks the current database row, but the Session may
                # already contain a stale TestTask instance in its identity map.
                # Reload the locked row's latest database values so lifecycle
                # decisions are based on current state, not cached ORM state.
                .execution_options(populate_existing=True)
            )
        else:
            stmt = select(TestTask).where(TestTask.id == task_id)

        test_task = self.session.scalar(stmt)
        return test_task

    def refresh(self, test_task: TestTask) -> None:
        """Read back persisted values without finalizing a transaction."""
        self.session.refresh(test_task)
