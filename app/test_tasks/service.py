"""Task creation, detail queries and transactional lifecycle updates."""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.transaction import transaction
from app.devices.model import DeviceStatus
from app.devices.repository import DeviceRepository
from app.devices.service import DeviceNotFoundError
from app.test_tasks.model import TestTask, TestTaskStatus
from app.test_tasks.repository import TestTaskRepository
from app.test_tasks.schema import TestTaskCreate, TestTaskUpdate


class TestTaskNotFoundError(Exception):
    """The requested UUID does not identify a stored task."""


class InactiveDeviceError(Exception):
    """A new task cannot be created for an inactive Device."""


class InvalidTestTaskStateError(Exception):
    """The requested transition is outside the permitted lifecycle."""


def create_test_task(session: Session, data: TestTaskCreate) -> TestTask:
    """Lock an active Device and commit one new pending task."""
    repo_device = DeviceRepository(session)
    repo_test_task = TestTaskRepository(session)

    with transaction(session):
        device = repo_device.get(data.device_id, for_update=True)

        if device is None:
            raise DeviceNotFoundError(
                "Device not found",
            )

        if device.status == DeviceStatus.INACTIVE:
            raise InactiveDeviceError(
                "Device is inactive",
            )

        test_task = TestTask(
            device_id=data.device_id,
            name=data.name,
            summary=data.summary,
        )
        repo_test_task.add(test_task)

    try:
        repo_test_task.refresh(test_task)
    except SQLAlchemyError:
        # Clean up failed read-back; the successful write is already committed.
        session.rollback()
        raise

    return test_task


def get_test_task(session: Session, task_id: UUID) -> TestTask:
    """Read one task without committing or loading its Device relationship."""

    repo_test_task = TestTaskRepository(session)

    test_task = repo_test_task.get(task_id, for_update=False)

    if test_task is None:
        raise TestTaskNotFoundError(
            "Task not found",
        )

    return test_task


def update_test_task(session: Session, task_id: UUID, data: TestTaskUpdate) -> TestTask:
    """Lock the task and atomically apply supplied fields and valid transitions."""
    repo_test_task = TestTaskRepository(session)

    with transaction(session):
        test_task = repo_test_task.get(task_id, for_update=True)

        if test_task is None:
            raise TestTaskNotFoundError(
                "Task not found",
            )

        updates = data.model_dump(exclude_unset=True)

        if "status" in updates:
            new_status = updates["status"]
            current_status = test_task.status

            if new_status != current_status:
                if current_status == TestTaskStatus.PENDING:
                    if new_status not in (
                        TestTaskStatus.RUNNING,
                        TestTaskStatus.CANCELLED,
                    ):
                        raise InvalidTestTaskStateError(
                            "Invalid test task state transition"
                        )

                elif current_status == TestTaskStatus.RUNNING:
                    if new_status not in (
                        TestTaskStatus.PASSED,
                        TestTaskStatus.FAILED,
                        TestTaskStatus.CANCELLED,
                    ):
                        raise InvalidTestTaskStateError(
                            "Invalid test task state transition"
                        )

                else:
                    raise InvalidTestTaskStateError(
                        "Invalid test task state transition"
                    )

                now_utc = datetime.now(UTC)

                if (
                    current_status == TestTaskStatus.PENDING
                    and new_status == TestTaskStatus.RUNNING
                ):
                    test_task.started_at = max(
                        now_utc,
                        test_task.requested_at,
                    )

                elif (
                    current_status == TestTaskStatus.PENDING
                    and new_status == TestTaskStatus.CANCELLED
                ):
                    test_task.finished_at = max(
                        now_utc,
                        test_task.requested_at,
                    )

                elif current_status == TestTaskStatus.RUNNING:
                    # The persisted running-state CHECK guarantees a start time.
                    started_at = cast(datetime, test_task.started_at)

                    test_task.finished_at = max(
                        now_utc,
                        test_task.requested_at,
                        started_at,
                    )

                test_task.status = new_status

        if "summary" in updates:
            test_task.summary = updates["summary"]

    try:
        repo_test_task.refresh(test_task)

    except SQLAlchemyError:
        # Clean up failed read-back; the successful write is already committed.
        session.rollback()
        raise

    return test_task
